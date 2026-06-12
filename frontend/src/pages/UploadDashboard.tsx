// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { Block, Grid, GridItem, PageHeader, Panel } from "@kui/react";
import CollectionList from "../components/collections/CollectionList";
import { useCollections } from "../api/useCollectionsApi";
import type { Collection } from "../types/collections";

export default function UploadDashboard() {
  const { data: collections = [] } = useCollections();
  const documentCount = (collections as Collection[]).reduce(
    (total: number, collection: Collection) => total + (collection.collection_info?.number_of_files ?? 0),
    0
  );

  return (
    <Grid cols={12} gap="density-lg" padding="density-lg">
      <GridItem cols={12}>
        <Block padding="density-lg">
          <PageHeader
            slotHeading="Document Upload"
            slotSubheading={`${collections.length} collections / ${documentCount} documents`}
          />
        </Block>
      </GridItem>

      <GridItem cols={12}>
        <Panel>
          <Block
            style={{
              height: "calc(100vh - 190px)",
              minHeight: "520px",
              overflow: "hidden",
            }}
          >
            <CollectionList />
          </Block>
        </Panel>
      </GridItem>
    </Grid>
  );
}
