import React from "react";
import IOReadCard from "./IOReadCard";
import IOWriteCard from "./IOWriteCard";

const IOPage = () => {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">File I/O task</h2>
        <p className="text-muted-foreground">
          Manually trigger read/write workloads on the mounted volume before
          load testing.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <IOReadCard />
        <IOWriteCard />
      </div>
    </div>
  );
};

export default IOPage;
