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

import { useState, useRef } from "react";
import { useChatStore } from "../../store/useChatStore";
import { useImageAttachmentStore, fileToBase64, isValidImageFile, MAX_IMAGE_SIZE } from "../../store/useImageAttachmentStore";
import { useToastStore } from "../../store/useToastStore";
import { Dropdown, Modal, Button, Flex, Text } from "@kui/react";
import { Image, Plus, Trash2 } from "lucide-react";

export const ChatActionsMenu = () => {
  const { messages, clearMessages } = useChatStore();
  const { addImage } = useImageAttachmentStore();
  const { showToast } = useToastStore();
  const [showConfirmModal, setShowConfirmModal] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const fileInputId = "chat-image-upload-input";

  const handleClearChatRequest = () => {
    if (messages.length > 0) {
      setShowConfirmModal(true);
    }
  };

  const handleConfirmClear = () => {
    clearMessages();
    setShowConfirmModal(false);
  };

  const handleCancelClear = () => {
    setShowConfirmModal(false);
  };

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    for (const file of Array.from(files)) {
      if (!isValidImageFile(file)) {
        showToast(`"${file.name}" is not a valid file`, "warning");
        continue;
      }

      if (file.size > MAX_IMAGE_SIZE) {
        showToast(`"${file.name}" is too large (max 10MB)`, "warning");
        continue;
      }

      try {
        const base64 = await fileToBase64(file);
        addImage(base64, file.name);
      } catch (error) {
        console.error("Failed to read image file:", error);
        showToast(`Failed to read "${file.name}"`, "error");
      }
    }

    // Reset input so the same file can be selected again
    e.target.value = "";
  };

  const hasMessages = messages.length > 0;

  // Using a label as the dropdown item content for "Add image" - this is a native
  // browser pattern that reliably triggers file inputs without timing issues
  const dropdownItems = [
    {
      // Wrap in label to make the entire item clickable for file selection
      children: (
        <label 
          htmlFor={fileInputId} 
          style={{ 
            display: 'flex', 
            alignItems: 'center', 
            gap: '8px',
            cursor: 'pointer',
            width: '100%',
            margin: '-8px -12px',
            padding: '8px 12px',
          }}
        >
          <Image size={16} />
          Add image
        </label>
      ),
      // No onSelect needed - the label handles the file input trigger
    },
    {
      children: "Clear chat",
      slotLeft: <Trash2 size={16} />,
      disabled: !hasMessages,
      danger: true,
      onSelect: handleClearChatRequest
    }
  ];

  return (
    <>
      {/* Hidden file input for image upload */}
      <input
        ref={fileInputRef}
        id={fileInputId}
        type="file"
        accept="image/jpeg,image/jpg,image/png,image/gif,image/webp"
        multiple
        onChange={handleFileChange}
        style={{ display: "none" }}
        aria-label="Upload image"
      />

      <Dropdown
        items={dropdownItems}
        size="small"
        side="top"
        align="start"
        aria-label="Chat options"
        style={{
          color: 'var(--text-color-subtle)'
        }}
        attributes={{
          DropdownContent: {
            style: {
              marginBottom: '8px'
            }
          }
        }}
      >
        <Plus size={14} />
      </Dropdown>

      <Modal
        open={showConfirmModal}
        onOpenChange={setShowConfirmModal}
        slotHeading="Clear Chat"
        slotFooter={
          <Flex align="center" justify="end" gap="density-sm">
            <Button kind="tertiary" onClick={handleCancelClear}>
              Cancel
            </Button>
            <Button color="danger" onClick={handleConfirmClear}>
              Clear Chat
            </Button>
          </Flex>
        }
      >
        <Text>
          Are you sure you want to clear all chat messages? This action cannot be undone.
        </Text>
      </Modal>
    </>
  );
}; 
