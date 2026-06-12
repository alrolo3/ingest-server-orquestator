// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent } from '../../../test/utils';
import Header from '../Header';

// Mock react-router-dom hooks
const mockNavigate = vi.fn();

vi.mock('react-router-dom', async (importOriginal) => {
  const actual = await importOriginal<typeof import('react-router-dom')>();
  return {
    ...actual,
    useNavigate: () => mockNavigate,
  };
});

// Mock NotificationBell component
vi.mock('../../notifications/NotificationBell', () => ({
  default: () => <div data-testid="notification-bell">Bell</div>
}));

// Mock NvidiaLogo component
vi.mock('../../icons/NvidiaLogo', () => ({
  default: () => <svg data-testid="nv-logo-element">Logo</svg>
}));

describe('Header', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe('Basic Rendering', () => {
    it('renders logo and title', () => {
      render(<Header />);
      
      expect(screen.getByTestId('nv-logo-element')).toBeInTheDocument();
      expect(screen.getByText('Ingest Server Orchestrator')).toBeInTheDocument();
    });

    it('renders notification bell', () => {
      render(<Header />);
      expect(screen.getByTestId('notification-bell')).toBeInTheDocument();
    });

    it('does not render chat or settings actions', () => {
      render(<Header />);
      expect(screen.queryByRole('button', { name: /settings/i })).not.toBeInTheDocument();
      expect(screen.queryByRole('button', { name: /chat/i })).not.toBeInTheDocument();
    });
  });

  describe('Navigation Behavior', () => {
    it('renders KUI AppBar with logo', () => {
      render(<Header />);
      
      expect(screen.getByTestId('nv-logo-element')).toBeInTheDocument();
      expect(screen.getByText('Ingest Server Orchestrator')).toBeInTheDocument();
    });

    it('navigates home when the title is clicked', () => {
      render(<Header />);
      
      fireEvent.click(screen.getByText('Ingest Server Orchestrator'));
      
      expect(mockNavigate).toHaveBeenCalledWith('/');
    });
  });

  describe('Button Interactions', () => {
    it('renders logo element', () => {
      render(<Header />);
      
      expect(screen.getByTestId('nv-logo-element')).toBeInTheDocument();
    });

    it('has no settings button', () => {
      render(<Header />);
      expect(screen.queryByRole('button', { name: /settings/i })).not.toBeInTheDocument();
    });
  });
});
