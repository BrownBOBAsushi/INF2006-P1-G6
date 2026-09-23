import { act, render, screen } from '@testing-library/react';
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
