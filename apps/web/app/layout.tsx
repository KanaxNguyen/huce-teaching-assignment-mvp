import type { Metadata } from "next";
import Script from "next/script";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL ?? "http://127.0.0.1:3000"),
  title: "HUCE TKB — Phân công giảng dạy 2026–2027",
  description: "Nhập dữ liệu Excel, quản lý ràng buộc, tối ưu phân công và xuất thời khóa biểu cho Bộ môn Toán học HUCE.",
  openGraph: {
    title: "HUCE TKB — Phân công giảng dạy 2026–2027",
    description: "MVP quản lý phân công giảng dạy, seminar và thời khóa biểu có ràng buộc.",
    images: [{ url: "/og.png", width: 1200, height: 630, alt: "HUCE TKB" }],
    locale: "vi_VN",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "HUCE TKB",
    description: "Phân công giảng dạy 2026–2027",
    images: ["/og.png"],
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="vi" suppressHydrationWarning>
      <head>
        <Script id="huce-theme-init" strategy="beforeInteractive">
          {`(() => {
            try {
              const saved = localStorage.getItem("huce-tkb-theme");
              const theme = saved === "light" || saved === "dark"
                ? saved
                : (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
              document.documentElement.dataset.theme = theme;
              document.documentElement.style.colorScheme = theme;
            } catch {
              document.documentElement.dataset.theme = "light";
            }
          })();`}
        </Script>
      </head>
      <body>{children}</body>
    </html>
  );
}
