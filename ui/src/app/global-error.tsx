'use client';

import * as Sentry from '@sentry/nextjs';
import NextError from 'next/error';
import { useEffect } from 'react';

export default function GlobalError({
  error
}: {
  error: Error & { digest?: string };
}) {
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);

  const showDevDetails = process.env.NODE_ENV !== 'production';

  return (
    <html>
      <body className='bg-background text-foreground'>
        {showDevDetails ? (
          <main className='mx-auto flex min-h-screen max-w-4xl flex-col gap-4 px-6 py-10'>
            <h1 className='text-2xl font-semibold'>Internal Server Error</h1>
            <p className='text-muted-foreground text-sm'>
              Local dev error details are shown here to make request-boundary failures diagnosable.
            </p>
            <div className='rounded-md border p-4'>
              <p className='text-sm font-medium'>Message</p>
              <pre className='mt-2 overflow-auto whitespace-pre-wrap text-xs'>
                {error.message || 'Unknown error'}
              </pre>
            </div>
            {error.digest && (
              <div className='rounded-md border p-4'>
                <p className='text-sm font-medium'>Digest</p>
                <pre className='mt-2 overflow-auto whitespace-pre-wrap text-xs'>
                  {error.digest}
                </pre>
              </div>
            )}
            {error.stack && (
              <div className='rounded-md border p-4'>
                <p className='text-sm font-medium'>Stack</p>
                <pre className='mt-2 overflow-auto whitespace-pre-wrap text-xs'>
                  {error.stack}
                </pre>
              </div>
            )}
          </main>
        ) : (
          /* `NextError` is the default Next.js error page component. Its type
          definition requires a `statusCode` prop. However, since the App Router
          does not expose status codes for errors, we simply pass 0 to render a
          generic error message. */
          <NextError statusCode={0} />
        )}
      </body>
    </html>
  );
}
