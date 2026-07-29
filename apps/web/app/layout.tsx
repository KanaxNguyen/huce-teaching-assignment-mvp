import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HUCE Teaching Assignment",
  description: "Phân công giảng dạy có ràng buộc cho Bộ môn Toán học.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}

