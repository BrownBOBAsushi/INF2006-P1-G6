import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { AuthPreview } from './AuthPreview';
import { LoginLayout } from './LoginLayout';

function mockMotionPreference(matches: boolean) {
  const original = window.matchMedia;
  Object.defineProperty(window, 'matchMedia', {
    configurable: true,
    value: (query: string) => ({
      matches,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
  return () => {
    if (original) Object.defineProperty(window, 'matchMedia', { configurable: true, value: original });
    else Reflect.deleteProperty(window, 'matchMedia');
  };
}

test('hero role rotates vertically and respects reduced motion', () => {
  vi.useFakeTimers();
  const restore = mockMotionPreference(false);
  try {
    const first = render(<LoginLayout open={false} onOpen={() => {}} onClose={() => {}}><button>Google</button></LoginLayout>);
    expect(screen.getByTestId('hero-role')).toHaveTextContent('software engineer.');
    act(() => { vi.advanceTimersByTime(2600); });
    expect(screen.getByTestId('hero-role')).toHaveTextContent('data scientist.');
    act(() => { vi.advanceTimersByTime(2600); });
    expect(screen.getByTestId('hero-role')).toHaveTextContent('financial analyst.');
    first.unmount();
  } finally {
    restore();
    vi.useRealTimers();
  }

  const reducedRestore = mockMotionPreference(true);
  vi.useFakeTimers();
  try {
    render(<LoginLayout open={false} onOpen={() => {}} onClose={() => {}}><button>Google</button></LoginLayout>);
    act(() => { vi.advanceTimersByTime(10000); });
    expect(screen.getByTestId('hero-role')).toHaveTextContent('software engineer.');
  } finally {
    reducedRestore();
    vi.useRealTimers();
  }
});

test('email auth preview labels fields, toggles password visibility, and confirms no credentials were sent', async () => {
  const user = userEvent.setup();
  render(<AuthPreview googleControl={<button>Continue with Google</button>} busy={false} activity="idle" error={null} onRetry={() => {}} />);
  await user.type(screen.getByLabelText('Email address'), 'student@example.test');
  await user.type(screen.getByLabelText('Password'), 'password123');
  await user.click(screen.getByRole('button', { name: 'Show password' }));
  expect(screen.getByLabelText('Password')).toHaveAttribute('type', 'text');
  await user.click(screen.getByRole('button', { name: 'Sign in' }));
  expect(screen.getByRole('status')).toHaveTextContent('Preview only — credentials were not sent.');
  await user.click(screen.getByRole('button', { name: 'Create one' }));
  expect(screen.getByLabelText('Name')).toBeInTheDocument();
});

test('forgot account preview confirms locally without claiming an email was sent', async () => {
  const user = userEvent.setup();
  render(<AuthPreview googleControl={<button>Continue with Google</button>} busy={false} activity="idle" error={null} onRetry={() => {}} />);
  await user.click(screen.getByRole('button', { name: 'Forgot email or password?' }));
  await user.type(screen.getByLabelText('Email address'), 'student@example.test');
  await user.click(screen.getByRole('button', { name: 'Send reset link' }));
  expect(screen.getByRole('status')).toHaveTextContent('Reset preview complete');
  expect(screen.getByRole('status')).toHaveTextContent('No email was sent.');
});
