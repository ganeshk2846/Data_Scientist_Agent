import { Component, type ErrorInfo, type ReactNode } from 'react';
import { AlertTriangle, RefreshCw } from 'lucide-react';
import { Button } from './Button';
import { Card } from './Card';

interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  onReset?: () => void;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, ErrorBoundaryState> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  override componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    console.error('ErrorBoundary caught an error:', error, errorInfo);
  }

  handleReset = () => {
    this.setState({ hasError: false, error: null });
    this.props.onReset?.();
  };

  override render() {
    if (this.state.hasError) {
      if (this.props.fallback) {
        return this.props.fallback;
      }
      return (
        <Card tone="flat" className="p-6 edge-accent">
          <div className="flex items-start gap-4">
            <div className="rounded-full bg-rose-500/10 p-2 text-rose-500">
              <AlertTriangle className="h-6 w-6" />
            </div>
            <div className="flex-1 space-y-2">
              <h2 className="text-base font-semibold text-ink">Something went wrong</h2>
              <p className="text-sm text-ink-muted">
                {this.state.error?.message || 'An unexpected error occurred while rendering.'}
              </p>
              <div className="pt-2">
                <Button variant="quiet" onClick={this.handleReset}>
                  <RefreshCw className="mr-2 h-4 w-4" />
                  Try again
                </Button>
              </div>
            </div>
          </div>
        </Card>
      );
    }
    return this.props.children;
  }
}
