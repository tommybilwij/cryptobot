import "./globals.css";

export const metadata = {
  title: "Cryptobot Strategy Lab",
  description: "Profile management + live runner monitoring",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen">
        <nav className="border-b border-zinc-800 px-6 py-3 flex gap-6 text-sm">
          <a href="/" className="font-semibold">
            Cryptobot
          </a>
          <a href="/profiles" className="hover:text-blue-400">
            Profiles
          </a>
          <a href="/oms" className="hover:text-blue-400">
            OMS
          </a>
          <a href="/live" className="hover:text-blue-400">
            Live
          </a>
          <a href="/audit" className="hover:text-blue-400">
            Audit
          </a>
          <a href="/exchanges" className="hover:text-blue-400">
            Exchanges
          </a>
        </nav>
        <main className="p-6">{children}</main>
      </body>
    </html>
  );
}
