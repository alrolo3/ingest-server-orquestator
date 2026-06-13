// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "../../../test/utils";
import { TaskPoller } from "../TaskPoller";

const mocks = vi.hoisted(() => ({
  queryResult: {
    data: null as unknown,
    isLoading: true,
    error: null as Error | null,
  },
  updateTaskNotification: vi.fn(),
  getAllNotifications: vi.fn(() => []),
  removeNotification: vi.fn(),
}));

vi.mock("../../../api/useIngestionTasksApi", () => ({
  useIngestionTasks: () => mocks.queryResult,
}));

vi.mock("../../../store/useNotificationStore", () => ({
  useNotificationStore: () => ({
    updateTaskNotification: mocks.updateTaskNotification,
    getAllNotifications: mocks.getAllNotifications,
    removeNotification: mocks.removeNotification,
  }),
}));

const pendingTask = (documentsCompleted: number) => ({
  id: "task-123",
  collection_name: "open-rag-embeddings-v4",
  created_at: "2026-06-12T00:00:00Z",
  state: "PENDING" as const,
  documents: ["one.pdf", "two.pdf", "three.pdf"],
  result: {
    message: `${documentsCompleted}/3 documents completed.`,
    total_documents: 3,
    documents:
      documentsCompleted > 0
        ? [
            {
              document_id: "doc-1",
              document_name: "one.pdf",
              size_bytes: 1024,
            },
          ]
        : [],
    failed_documents: [],
    documents_completed: documentsCompleted,
    batches_completed: documentsCompleted,
  },
});

describe("TaskPoller", () => {
  beforeEach(() => {
    mocks.queryResult.data = null;
    mocks.queryResult.isLoading = true;
    mocks.queryResult.error = null;
    mocks.updateTaskNotification.mockClear();
    mocks.getAllNotifications.mockClear();
    mocks.removeNotification.mockClear();
  });

  it("renders nothing", () => {
    const { container } = render(<TaskPoller taskId="test-task" />);
    expect(container.firstChild).toBeNull();
  });

  it("updates pending task notifications when document progress changes", async () => {
    mocks.queryResult.data = pendingTask(0);
    mocks.queryResult.isLoading = false;

    const { rerender } = render(<TaskPoller taskId="task-123" />);

    await waitFor(() => {
      expect(mocks.updateTaskNotification).toHaveBeenCalledTimes(1);
    });

    mocks.queryResult.data = pendingTask(1);
    rerender(<TaskPoller taskId="task-123" />);

    await waitFor(() => {
      expect(mocks.updateTaskNotification).toHaveBeenCalledTimes(2);
    });

    expect(mocks.updateTaskNotification).toHaveBeenLastCalledWith(
      "task-123",
      expect.objectContaining({
        state: "PENDING",
        result: expect.objectContaining({
          message: "1/3 documents completed.",
          documents_completed: 1,
          total_documents: 3,
          documents: [
            expect.objectContaining({
              document_name: "one.pdf",
            }),
          ],
        }),
      })
    );
  });
});
