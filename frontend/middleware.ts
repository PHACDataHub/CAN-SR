import { NextResponse, NextRequest } from "next/server";
import { match } from "@formatjs/intl-localematcher";
import Negotiator from "negotiator";

const locales = ["en", "fr"];
const defaultLocale = "en"
 
function getLocale(request: NextRequest) {
  // Get Accept-Language header
  const headers = { "accept-language": request.headers.get("accept-language") ?? "" };
  // Get requested locales (sorted in decreasing preference)
  const requestedLocales = new Negotiator({ headers }).languages();

  // Match to en or fr
  return match(requestedLocales, locales, defaultLocale);
}
 
export function middleware(request: NextRequest) {
  // Check if there is any supported locale in the pathname
  const { pathname } = request.nextUrl;
  const pathnameHasLocale = locales.some(
    (locale) => pathname.startsWith(`/${locale}/`) || pathname === `/${locale}`
  );
 
  if (pathnameHasLocale) return;
 
  // Redirect if there is no locale
  const locale = getLocale(request);
  request.nextUrl.pathname = `/${locale}${pathname}`;
  // e.g. incoming request is /login
  // The new URL is now /en/login
  return NextResponse.redirect(request.nextUrl);
}
 
export const config = {
  matcher: [
    // Skip all internal paths (_next)
    '/((?!_next).*)',
    // Optional: only run on root (/) URL
    // '/'
  ],
}