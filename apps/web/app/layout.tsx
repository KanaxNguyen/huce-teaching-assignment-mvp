import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "HUCE · Phân công giảng dạy",
  description: "Không gian lập lịch và phân công giảng dạy dành cho trưởng bộ môn.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
