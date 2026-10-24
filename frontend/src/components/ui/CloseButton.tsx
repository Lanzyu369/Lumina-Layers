import { forwardRef } from "react";
import { XMarkIcon } from "@heroicons/react/24/outline";

interface CloseButtonProps {
  label: string;
  onClick: () => void;
  "data-testid"?: string;
}

  return (
      <XMarkIcon aria-hidden="true" className="h-5 w-5" />
    </button>
  );
});

export default CloseButton;
