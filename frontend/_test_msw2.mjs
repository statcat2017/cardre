import { setupServer } from "msw/node";
import { http, HttpResponse } from "msw";

// Test with path-only pattern
const server = setupServer(
  http.get("/projects/:projectId/branches", ({ params }) => {
    console.log("PATH-ONLY MATCHED:", JSON.stringify(params));
    return HttpResponse.json({ branches: [] });
  }),
  http.get("http://127.0.0.1:8752/projects/:projectId/runs", ({ params }) => {
    console.log("FULL-URL MATCHED:", JSON.stringify(params));
    return HttpResponse.json({ runs: [] });
  }),
);

server.listen({ onUnhandledRequest: "error" });

async function run() {
  try {
    console.log("Testing path-only pattern...");
    const r1 = await fetch("http://127.0.0.1:8752/projects/prj1/branches?status=active");
    const d1 = await r1.json();
    console.log("Result:", d1);
  } catch(e) {
    console.log("Path-only FAILED:", e.message);
  }
  try {
    console.log("Testing full-url pattern...");
    const r2 = await fetch("http://127.0.0.1:8752/projects/prj1/runs");
    const d2 = await r2.json();
    console.log("Result:", d2);
  } catch(e) {
    console.log("Full-url FAILED:", e.message);
  }
  server.close();
}
run();
