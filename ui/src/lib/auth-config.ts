export const clerkPublishableKey =
  process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY?.trim() ?? '';

export const clerkAuthEnabled =
  clerkPublishableKey.length > 0 ||
  String(process.env.NEXT_PUBLIC_FXHE_UI_REQUIRE_AUTH || '').toLowerCase() === 'true';