import type { Metadata } from 'next'

export const metadata: Metadata = {
  title: 'Price Radar',
  description: 'Track prices across the web',
}

export default function RootLayout({
  children,
}: {
  children: React.ReactNode
}) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  )
}
