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

import { AppBar, Text, Flex } from "@kui/react";
import NotificationBell from "../notifications/NotificationBell";
import NvidiaLogo from "../icons/NvidiaLogo";
import { useNavigate } from "react-router-dom";

/**
 * Application header component with navigation and branding.
 * 
 * Uses KUI AppBar component with integrated NVIDIA branding,
 * application title, and navigation elements including settings button
 * and notification bell. Handles routing between different sections.
 * 
 * @returns Header component using KUI AppBar with navigation elements
 */
export default function Header() {
  const navigate = useNavigate();

  const handleLogoClick = () => {
    navigate("/");
  };

  return (
    <AppBar
      slotLeft={
        <Flex align="center" gap="density-md">
          <div onClick={handleLogoClick} style={{ cursor: 'pointer' }}>
            <NvidiaLogo height="20px" />
          </div>
          <Text kind="title/xs" onClick={handleLogoClick} style={{ cursor: 'pointer' }}>
            Ingest Server Orchestrator
          </Text>
        </Flex>
      }
      slotRight={
        <Flex align="center" gap="2">
          <NotificationBell />
        </Flex>
      }
    />
  );
}
