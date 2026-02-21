import { BrowserRouter, Routes, Route } from "react-router-dom";
import Layout from "./components/Layout";
import Dashboard from "./pages/Dashboard";
import JobWizard from "./pages/JobWizard";

function App() {
  return (
    <BrowserRouter>
      <Layout>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/jobs/new" element={<JobWizard />} />
          <Route path="/jobs/:id" element={<JobWizard />} />
        </Routes>
      </Layout>
    </BrowserRouter>
  );
}

export default App;
