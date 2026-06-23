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

import React from 'react';
import logoSrc from '../../assets/centro-apoyo-tecnico.png';

interface NvidiaLogoProps {
  height?: string;
  alt?: string;
  className?: string;
}

export default function NvidiaLogo({ 
  height = '20px', 
  alt = 'Centro de Apoyo Tecnico logo',
  className = ''
}: NvidiaLogoProps): React.ReactElement {
  return (
    <img
      src={logoSrc}
      alt={alt}
      className={`nv-logo-element ${className}`.trim()}
      data-testid="nv-logo-element" 
      style={{ display: 'block', height, width: 'auto' }}
    />
  );
}
