import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router';
import { ApiClient } from './api/client';
import { App } from './App';
import './styles.css';

async function start() {
  const mock = __MOCK__ ? await import('./dev/mockFetch') : undefined;
  const client = new ApiClient(mock ? mock.createMockFetch() : fetch);
  createRoot(document.getElementById('root')!).render(
    <BrowserRouter><App client={client} mock={__MOCK__} SignInControl={mock?.MockSignIn} /></BrowserRouter>,
  );
}
void start();
