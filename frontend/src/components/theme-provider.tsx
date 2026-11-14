import React, { createContext, useContext, useEffect } from 'react';

type Theme = 'dark';

interface ThemeProviderState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeProviderState>({
  theme: 'dark',
  setTheme: () => null,
  toggleTheme: () => null,
});

export const ThemeProvider: React.FC<{ children: React.ReactNode; defaultTheme?: Theme }> = ({
  children,
}) => {
  useEffect(() => {
    const root = window.document.documentElement;
    root.classList.remove('light');
    root.classList.add('dark');
    try {
      localStorage.setItem('geollm_theme', 'dark');
    } catch {}
  }, []);

  return (
    <ThemeContext.Provider
      value={{
        theme: 'dark',
        setTheme: () => null,
        toggleTheme: () => null,
      }}
    >
      {children}
    </ThemeContext.Provider>
  );
};

export const useTheme = () => useContext(ThemeContext);
