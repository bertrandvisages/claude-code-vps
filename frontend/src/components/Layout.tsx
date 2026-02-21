import type { ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { Film, ArrowLeft } from "lucide-react";

export default function Layout({ children }: { children: ReactNode }) {
  const location = useLocation();
  const isHome = location.pathname === "/";

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200">
        <div className="max-w-4xl mx-auto px-6 py-4 flex items-center gap-4">
          {!isHome && (
            <Link
              to="/"
              className="text-gray-500 hover:text-gray-700 transition-colors"
            >
              <ArrowLeft className="w-5 h-5" />
            </Link>
          )}
          <Link to="/" className="flex items-center gap-2">
            <Film className="w-6 h-6 text-indigo-600" />
            <h1 className="text-xl font-semibold text-gray-900">
              Video Montage
            </h1>
          </Link>
        </div>
      </header>
      <main className="max-w-4xl mx-auto px-6 py-8">{children}</main>
    </div>
  );
}
