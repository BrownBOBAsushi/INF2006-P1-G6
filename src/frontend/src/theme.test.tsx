import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router';
import { ApiClient } from './api/client';
import { App, THEME_STORAGE_KEY } from './App';
import { MockSignIn, createMockFetch } from './dev/mockFetch';

test('landing theme preference persists and auth CTA opens a focus-trapped dialog', async () => {
  window.localStorage.clear();
  const user = userEvent.setup();
  const app = <MemoryRouter><App client={new ApiClient(createMockFetch())} mock SignInControl={MockSignIn} /></MemoryRouter>;
  const { rerender } = render(app);

  const theme = await screen.findByRole('button', { name: 'Switch to light theme' });
  await user.click(theme);
  expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
  expect(screen.getByRole('button', { name: 'Switch to dark theme' })).toBeInTheDocument();
  const explore = screen.getByRole('button', { name: 'Explore opportunities' });
  await user.click(explore);
  expect(screen.getByRole('dialog', { name: 'Find an internship that fits' })).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Enter synthetic preview' })).toHaveFocus();
  rerender(app);
  await user.keyboard('{Escape}');
  expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  expect(explore).toHaveFocus();
});
