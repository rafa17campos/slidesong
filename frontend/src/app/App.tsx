import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { createBrowserRouter, Navigate, RouterProvider } from "react-router";

import { ApiError } from "@/api/client";
import { ToastProvider } from "@/components/ui/Toast";
import { Home } from "@/routes/Home";
import { LearningPage } from "@/routes/Learning";
import { ProjectPage, ProjectRedirect } from "@/routes/Project";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5_000,
      retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2,
    },
  },
});

const router = createBrowserRouter(
  [
    { path: "/", element: <Home /> },
    { path: "/learning", element: <LearningPage /> },
    { path: "/aprendizaje", element: <Navigate to="/learning" replace /> }, // its first address
    { path: "/p/:pid", element: <ProjectRedirect /> },
    { path: "/p/:pid/:step", element: <ProjectPage /> },
  ],
  { basename: import.meta.env.BASE_URL.replace(/\/$/, "") },
);

export function App() {
  // a new language repaints everything (texts computed once and kept are made again)
  const { i18n } = useTranslation();
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider key={i18n.resolvedLanguage}>
        <RouterProvider router={router} />
      </ToastProvider>
    </QueryClientProvider>
  );
}
