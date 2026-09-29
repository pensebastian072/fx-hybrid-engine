import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server';
import { NextRequest, NextResponse, type NextFetchEvent } from 'next/server';

// Pages AND the API need a login when Clerk is on. /api/run starts a
// PowerShell job and /api/config rewrites YAML, so they must never be
// reachable by someone who is not signed in.
const isProtectedRoute = createRouteMatcher(['/dashboard(.*)', '/api(.*)']);

// Login is enforced whenever Clerk is configured. Without a publishable key:
//  - `next dev` runs open, as before;
//  - a production server refuses every request (503) unless it was started in
//    local mode (FXHE_UI_LOCAL_MODE=true, set by start.bat / start.sh, which
//    also bind 127.0.0.1). This keeps a keyless production deploy fail-closed.
// Set FXHE_UI_REQUIRE_AUTH=true to refuse to serve pages without Clerk at all.
const clerkConfigured = Boolean(
  (process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY || '').trim()
);
const requireAuth =
  clerkConfigured ||
  String(process.env.FXHE_UI_REQUIRE_AUTH || '').toLowerCase() === 'true';
const isProduction = process.env.NODE_ENV === 'production';

function localModeEnabled(): boolean {
  return String(process.env.FXHE_UI_LOCAL_MODE || '').toLowerCase() === 'true';
}

function textResponse(status: number, message: string): NextResponse {
  return new NextResponse(message, {
    status,
    headers: { 'content-type': 'text/plain; charset=utf-8' }
  });
}

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

// Cross-site request forgery guard. A web page you visit can make your browser
// POST to http://127.0.0.1:3055 (a text/plain POST needs no CORS preflight),
// which would let any site start runs or overwrite config. Browsers label
// every request with Sec-Fetch-Site and, for POSTs, Origin - refuse writes
// that did not come from this dashboard's own pages.
function isCrossSiteWrite(req: NextRequest): boolean {
  if (SAFE_METHODS.has(req.method)) {
    return false;
  }
  const site = req.headers.get('sec-fetch-site');
  if (site && site !== 'same-origin' && site !== 'none') {
    return true;
  }
  const origin = req.headers.get('origin');
  if (origin) {
    try {
      return new URL(origin).host !== req.headers.get('host');
    } catch {
      return true;
    }
  }
  return false; // non-browser clients (curl, scripts) send neither header
}

// DNS-rebinding guard for local mode: a remote site can point its own hostname
// at 127.0.0.1, but it cannot make the browser send Host: 127.0.0.1.
function isLoopbackHost(req: NextRequest): boolean {
  const host = (req.headers.get('host') || '').toLowerCase().replace(/:\d+$/, '');
  return host === '127.0.0.1' || host === 'localhost' || host === '[::1]';
}

// Created only when auth is required: clerkMiddleware() throws on construction
// if no publishable key is set, which took down every page in local mode.
const protectedProxy = requireAuth
  ? clerkMiddleware(async (auth, req: NextRequest) => {
      if (isProtectedRoute(req)) {
        await auth.protect();
      }
    })
  : null;

export default function proxy(req: NextRequest, event: NextFetchEvent) {
  if (isCrossSiteWrite(req)) {
    return textResponse(403, 'Cross-site request refused.');
  }
  if (protectedProxy) {
    return protectedProxy(req, event);
  }
  if (isProduction && !localModeEnabled()) {
    return textResponse(
      503,
      'Sign-in is not configured. Start the dashboard with start.bat / start.sh ' +
        '(local mode, this computer only) or add Clerk keys to ui/.env.local and rebuild.'
    );
  }
  if (!isLoopbackHost(req)) {
    return textResponse(403, 'Local mode only answers on 127.0.0.1 / localhost.');
  }
  return NextResponse.next();
}

export const config = {
  matcher: [
    // Skip Next.js internals and all static files, unless found in search params
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    // Always run for API routes
    '/(api|trpc)(.*)'
  ]
};
