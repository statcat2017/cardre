import React from 'react';
import { theme } from '../styles';

interface MessageBannerProps {
  message?: string | null;
  type?: 'error' | 'info' | 'success' | null;
}

export function MessageBanner({ message, type }: MessageBannerProps) {
  if (!message) return null;
  const colors = type === 'error'
    ? { bg: theme.redBg, text: theme.redText }
    : type === 'success'
      ? { bg: theme.greenBg, text: theme.greenText }
      : { bg: theme.blueBg, text: theme.blueText };
  return (
    <div
      style={{
        backgroundColor: colors.bg,
        color: colors.text,
        border: `1px solid ${theme.border}`,
        padding: '10px 16px',
        borderRadius: '6px',
        marginBottom: '16px',
      }}
    >
      {message}
    </div>
  );
}
