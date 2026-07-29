import React, {
  createContext,
  type ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react';

import {useLocation} from '@docusaurus/router';
import useBaseUrl from '@docusaurus/useBaseUrl';

const storageKey = 'ai-optimizer.visited-docs';

type VisitedDocsContextValue = {
  clearVisitedDocs: () => void;
  hasVisitedDoc: (href: string) => boolean;
  hasVisitedDocs: boolean;
};

const VisitedDocsContext = createContext<VisitedDocsContextValue | undefined>(
  undefined,
);

function normalizePath(path: string, baseUrl: string): string {
  const pathname = new URL(path, 'https://docs.example').pathname;
  const normalizedBaseUrl = baseUrl.replace(/\/$/, '');

  if (normalizedBaseUrl && pathname.startsWith(normalizedBaseUrl)) {
    return pathname.slice(normalizedBaseUrl.length) || '/';
  }

  return pathname;
}

function readVisitedDocs(): Set<string> {
  try {
    const storedPaths: unknown = JSON.parse(
      window.localStorage.getItem(storageKey) ?? '[]',
    );
    return new Set(
      Array.isArray(storedPaths)
        ? storedPaths.filter((path): path is string => typeof path === 'string')
        : [],
    );
  } catch {
    return new Set();
  }
}

export function VisitedDocsProvider({children}: {children: ReactNode}): ReactNode {
  const {pathname} = useLocation();
  const baseUrl = useBaseUrl('/');
  const [visitedDocs, setVisitedDocs] = useState<Set<string>>(() => new Set());

  useEffect(() => {
    const nextVisitedDocs = readVisitedDocs();
    nextVisitedDocs.add(normalizePath(pathname, baseUrl));
    window.localStorage.setItem(storageKey, JSON.stringify([...nextVisitedDocs]));
    setVisitedDocs(nextVisitedDocs);
  }, [baseUrl, pathname]);

  const clearVisitedDocs = useCallback(() => {
    window.localStorage.removeItem(storageKey);
    setVisitedDocs(new Set());
  }, []);

  const value = useMemo(
    () => ({
      clearVisitedDocs,
      hasVisitedDoc: (href: string) =>
        visitedDocs.has(normalizePath(href, baseUrl)),
      hasVisitedDocs: visitedDocs.size > 0,
    }),
    [baseUrl, clearVisitedDocs, visitedDocs],
  );

  return <VisitedDocsContext.Provider value={value}>{children}</VisitedDocsContext.Provider>;
}

export function useVisitedDocs(): VisitedDocsContextValue {
  const context = useContext(VisitedDocsContext);

  if (!context) {
    throw new Error('useVisitedDocs must be used within VisitedDocsProvider');
  }

  return context;
}
