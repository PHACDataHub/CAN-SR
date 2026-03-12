import '@/app/globals.css'
import { Inter } from 'next/font/google'
import { Toaster } from 'react-hot-toast'
import { UploadQueueProvider } from '@/components/files/upload-queue-context'
import { UploadQueueNotification } from '@/components/files/upload-queue-notification'
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
  params: Promise<{ lang: 'en' | 'fr' }>
}>) {
  const { lang } = await params
  const dictionary = await getDictionary(lang)

  return (
    <html lang={lang} className={inter.variable} suppressHydrationWarning>
      <body suppressHydrationWarning>
        <DictionaryProvider dictionary={dictionary}>
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
        </DictionaryProvider>
      </body>
    </html>
  )
}
