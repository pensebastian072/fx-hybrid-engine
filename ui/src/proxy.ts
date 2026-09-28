import { clerkMiddleware, createRouteMatcher } from '@clerk/nextjs/server';
import { NextRequest, NextResponse, type NextFetchEvent } from 'next/server';

const isProtectedRoute = createRouteMatcher(['/dashboard(.*)']);
// Login is enforced whenever Clerk is configured. Without a publishable key:
//  - `next dev` runs open, as before;
//  - a production server refuses every request (503) unless it was started in
//    local mode (FXHE_UI_LOCAL_MODE=true, set by start.bat / start.sh, which
//    also bind 127.0.0.1). This keeps a keyless production deploy fail-closed:
//    /api/run and /api/config must never be reachable without auth.
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
  if (protectedProxy) {
    return protectedProxy(req, event);
  }
  if (isProduction && !localModeEnabled()) {
    return new NextResponse(
      'Sign-in is not configured. Start the dashboard with start.bat / start.sh ' +
        '(local mode, this computer only) or add Clerk keys to ui/.env.local and rebuild.',
      { status: 503, headers: { 'content-type': 'text/plain; charset=utf-8' } }
    );
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
