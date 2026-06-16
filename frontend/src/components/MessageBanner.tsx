import React from 'react';

interface MessageBannerProps {
  message?: string | null;
  type?: 'error' | 'info' | 'success' | null;
}

export function MessageBanner({ message, type }: MessageBannerProps) {
  if (!message) return null;
  const bgColor = type === 'error' ? '#f8d7da' : type === 'success' ? '#d4edda' : '#d1ecf1';
  return <div style={{ backgroundColor: bgColor, color: '#0c5460', padding: '10px 16px', borderRadius: '6px', marginBottom: '16px' }}>{message}</div>;
}
