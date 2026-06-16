// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
// http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

import type { IngestionTask } from "../../types/api";
import { useTaskUtils } from "../../hooks/useTaskUtils";
import { Check, TriangleAlert, X } from "lucide-react";

const SpinnerIcon = () => (
  <div 
    className="w-4 h-4 animate-spin rounded-full border-2 border-brand border-t-transparent" 
    data-testid="spinner-icon"
  />
);

const SuccessIcon = () => (
  <div 
    className="w-4 h-4 rounded-full bg-feedback-success flex items-center justify-center"
    data-testid="success-icon"
  >
    <Check className="w-2.5 h-2.5 text-feedback-success-inverse" strokeWidth={3} />
  </div>
);

const WarningIcon = () => (
  <div 
    className="w-4 h-4 rounded-full bg-feedback-warning flex items-center justify-center"
    data-testid="warning-icon"
  >
    <TriangleAlert className="w-2.5 h-2.5 text-feedback-warning-inverse" strokeWidth={3} />
  </div>
);

const ErrorIcon = () => (
  <div 
    className="w-4 h-4 rounded-full bg-feedback-danger flex items-center justify-center"
    data-testid="error-icon"
  >
    <X className="w-2.5 h-2.5 text-feedback-danger-inverse" strokeWidth={3} />
  </div>
);

interface TaskStatusIconProps {
  state: string;
  task?: IngestionTask & { completedAt?: number; read?: boolean };
}

export const TaskStatusIcon = ({ state, task }: TaskStatusIconProps) => {
  const { getTaskStatus } = useTaskUtils();
  
  // If we have the full task, use the enhanced status logic
  if (task) {
    // Check for PENDING first
    if (state === "PENDING") {
      return <SpinnerIcon />;
    }
    
    const status = getTaskStatus(task);
    
    if (status.isPartial) {
      return <WarningIcon />;
    } else if (status.isSuccess) {
      return <SuccessIcon />;
    } else if (status.isFailed) {
      return <ErrorIcon />;
    }
  }

  // Fallback to simple state-based logic
  switch (state) {
    case "PENDING":
      return <SpinnerIcon />;
    case "FINISHED":
      return <SuccessIcon />;
    default:
      return <ErrorIcon />;
  }
}; 
