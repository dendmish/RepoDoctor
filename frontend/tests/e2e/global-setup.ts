import { createServer } from 'vite';

export default async function setup() {
  const previous = {
    enabled: process.env.VITE_ENABLE_MSW,
    scenario: process.env.VITE_MSW_SCENARIO,
  };
  process.env.VITE_ENABLE_MSW = 'true';
  process.env.VITE_MSW_SCENARIO = 'python';
  // Own the server in-process so teardown closes exactly this server, including
  // on Windows sandboxes where taskkill cannot enumerate child process trees.
  const server = await createServer({
    server: { host: '127.0.0.1', port: 5179, strictPort: true },
  });
  try {
    await server.listen();
  } catch (error) {
    await server.close();
    restoreEnvironment();
    throw error;
  }
  return async () => {
    try { await server.close(); }
    finally { restoreEnvironment(); }
  };
  function restoreEnvironment() {
    if (previous.enabled === undefined) delete process.env.VITE_ENABLE_MSW;
    else process.env.VITE_ENABLE_MSW = previous.enabled;
    if (previous.scenario === undefined) delete process.env.VITE_MSW_SCENARIO;
    else process.env.VITE_MSW_SCENARIO = previous.scenario;
  }
}
