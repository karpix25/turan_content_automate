import React from 'react';
import type {WordCue} from '../types';
import {lineClampStyle} from '../utils';

interface CueWordsProps {
  cueWords: WordCue[];
  theme: any;
}

export const CueWords: React.FC<CueWordsProps> = ({cueWords, theme}) => {
  if (cueWords.length === 0) {
    return null;
  }

  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: 10,
        marginTop: 14,
      }}
    >
      {cueWords.map((cue, index) => (
        <div
          key={`${cue.time}-${cue.text}-${index}`}
          style={{
            padding: '8px 14px',
            borderRadius: 999,
            color: theme.textMain,
            background: '#ffffff10',
            border: `1px solid ${theme.accent}66`,
            fontFamily: theme.fontMain,
            fontSize: 24,
            fontWeight: 620,
            ...lineClampStyle(1),
          }}
        >
          {cue.text}
        </div>
      ))}
    </div>
  );
};
