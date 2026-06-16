// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import { BrowserRouter, Navigate, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import UploadDashboard from "./pages/UploadDashboard";
import NewCollection from "./pages/NewCollection";
import Layout from "./components/layout/Layout";
import { ToastContainer } from "./components/ui/ToastContainer";
import { useHealthMonitoring } from "./hooks/useHealthMonitoring";

/**
 * React Query client configuration with default options.
 */
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
    },
  },
});

/**
 * App content component that initializes settings and monitors health.
 */
function AppContent() {
  useHealthMonitoring();
  
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<UploadDashboard />} />
        <Route path="/collections/new" element={<NewCollection />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Layout>
  );
}

/**
 * Main application component that sets up routing and provides React Query context.
 * 
 * @returns The main App component with routing and layout
 */
export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppContent />
      </BrowserRouter>
      <ToastContainer />
    </QueryClientProvider>
  );
}
