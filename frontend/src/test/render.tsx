import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, renderHook, type RenderOptions } from "@testing-library/react";
import type { ReactElement, ReactNode } from "react";
import { MemoryRouter } from "react-router-dom";

interface Options extends Omit<RenderOptions, "wrapper"> {
  route?: string;
  queryClient?: QueryClient;
}

function makeTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: Infinity, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
}

function makeWrapper(route: string, queryClient: QueryClient) {
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>{children}</MemoryRouter>
    </QueryClientProvider>
  );
}

export function renderWithProviders(
  ui: ReactElement,
  { route = "/", queryClient = makeTestQueryClient(), ...rest }: Options = {}
) {
  const Wrapper = makeWrapper(route, queryClient);
  return { queryClient, ...render(ui, { wrapper: Wrapper, ...rest }) };
}

export function renderHookWithProviders<TResult, TProps>(
  callback: (props: TProps) => TResult,
  {
    route = "/",
    queryClient = makeTestQueryClient(),
    ...rest
  }: Options & { initialProps?: TProps } = {}
) {
  const Wrapper = makeWrapper(route, queryClient);
  return { queryClient, ...renderHook(callback, { wrapper: Wrapper, ...rest }) };
}
