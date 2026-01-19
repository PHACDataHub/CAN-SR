'use client'

import { useState, useEffect } from 'react'

interface TypingAnimationProps {
  text: string
  speed?: number
  className?: string
  onComplete?: () => void
  showCursor?: boolean
  cursorChar?: string
  cursorClassName?: string
}

export function TypingAnimation({
  text,
  speed = 50,
  className = '',
  onComplete,
  showCursor = true,
  cursorChar = '|',
  cursorClassName = '',
}: TypingAnimationProps) {
  const [displayedText, setDisplayedText] = useState('')
  const [currentIndex, setCurrentIndex] = useState(0)
  const [isComplete, setIsComplete] = useState(false)
  const [showCursorState, setShowCursorState] = useState(true)

  useEffect(() => {
    if (currentIndex < text.length) {
      const timer = setTimeout(() => {
        setDisplayedText((prev) => prev + text[currentIndex])
        setCurrentIndex((prev) => prev + 1)
      }, speed)

      return () => clearTimeout(timer)
    } else if (!isComplete) {
      setIsComplete(true)
      onComplete?.()

      // Hide cursor immediately when typing completes so emoji can take its place
      setShowCursorState(false)
    }
  }, [currentIndex, text, speed, isComplete, onComplete])

  // Cursor blinking effect
  useEffect(() => {
    if (!showCursor) return

    const cursorTimer = setInterval(() => {
      setShowCursorState((prev) => !prev)
    }, 530) // Blink every 530ms for natural feel

    return () => clearInterval(cursorTimer)
  }, [showCursor])

  return (
    <span className={className}>
      {displayedText}
      {showCursor && !isComplete && (
        <span
          className={`inline-block transition-opacity duration-100 ${
            showCursorState ? 'opacity-100' : 'opacity-0'
          } ${cursorClassName}`}
          style={{
            width: '3px',
            height: '1.1em',
            backgroundColor: 'currentColor',
            marginLeft: '2px',
            verticalAlign: 'text-top',
            transform: 'translateY(0.1em)',
          }}
        >
          {cursorChar === '|' ? '' : cursorChar}
        </span>
      )}
    </span>
  )
}
