import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RLALab AI Research Assistant",
  description: "Internal research literature assistant — RLA Lab, Imperial College London",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-gray-50 text-gray-900 antialiased">
        {children}
      </body>
    </html>
  );
}
