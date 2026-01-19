'use client'

import { ChevronDown } from 'lucide-react'

interface ScrollToBottomButtonProps {
  onClick: () => void
  visible: boolean
}

export function ScrollToBottomButton({
  onClick,
  visible,
}: ScrollToBottomButtonProps) {
  if (!visible) return null

  return (
    <button
      onClick={onClick}
      className="scroll-to-bottom-btn absolute right-4 bottom-36 z-10 flex h-10 w-10 items-center justify-center rounded-full bg-white shadow-lg transition-all duration-300 hover:bg-gray-100 hover:shadow-md active:scale-95 md:right-8"
      aria-label="Scroll to bottom"
    >
      <div className="flex h-full w-full items-center justify-center rounded-full">
        <ChevronDown className="bounce-animation h-5 w-5 text-gray-600" />
      </div>
      <style jsx>{`
        @keyframes bounce {
          0%,
          100% {
            transform: translateY(0);
          }
          50% {
            transform: translateY(3px);
          }
        }
        .bounce-animation {
          animation: bounce 1.5s ease-in-out infinite;
        }
      `}</style>
    </button>
  )
}
