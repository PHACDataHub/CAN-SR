import '@/app/globals.css'
import { Inter } from 'next/font/google'
import { Toaster } from 'react-hot-toast'
import { UploadQueueProvider } from '@/components/files/upload-queue-context'
import { UploadQueueNotification } from '@/components/files/upload-queue-notification'
import RunAllFloatingPanel from '@/components/can-sr/RunAllFloatingPanel'
import { DictionaryProvider } from './DictionaryProvider'
import { getDictionary } from './dictionaries'

const inter = Inter({
  subsets: ['latin'],
  variable: '--font-inter',
})

export const metadata = {
  title: 'CAN-SR',
  description: 'An AI assistant for Systematic Reviews',
}

export default async function RootLayout({
  children,
  params,
}: Readonly<{
  children: React.ReactNode
  params: Promise<{ lang: string }>
}>) {
  const { lang } = await params
  const safeLang = lang === 'fr' ? 'fr' : 'en'
  const dictionary = await getDictionary(safeLang)

  return (
    <html lang={safeLang} className={inter.variable} suppressHydrationWarning>
      <body suppressHydrationWarning>
        <DictionaryProvider dictionary={dictionary}>
          <UploadQueueProvider>
            {children}
            <UploadQueueNotification />
            <RunAllFloatingPanel />
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
        </DictionaryProvider>
      </body>
    </html>
  )
}
