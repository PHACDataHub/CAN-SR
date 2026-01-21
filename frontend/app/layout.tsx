import '@/app/globals.css'
import { Inter } from 'next/font/google'
import { Toaster } from 'react-hot-toast'
import { UploadQueueProvider } from '@/components/files/upload-queue-context'
import { UploadQueueNotification } from '@/components/files/upload-queue-notification'

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
})

export const metadata = {
  title: 'CAN-SR',
  description: 'An AI assistant for Systematic Reviews',
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode
}>) {
  return (
    <html lang="en" className={inter.variable} suppressHydrationWarning>
      <body suppressHydrationWarning>
        <UploadQueueProvider>
          {children}
          <UploadQueueNotification />
          <Toaster
            position="top-right"
            toastOptions={{
              duration: 4000,
              style: {
                background: '#363636',
                color: '#fff',
              },
              success: {
                duration: 3000,
                iconTheme: {
                  primary: '#10b981',
                  secondary: '#fff',
                },
              },
              error: {
                duration: 5000,
                iconTheme: {
                  primary: '#ef4444',
                  secondary: '#fff',
                },
              },
            }}
          />
        </UploadQueueProvider>
      </body>
    </html>
  )
}
