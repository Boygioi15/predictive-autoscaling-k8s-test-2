import React from "react";
import { Button } from "@/components/ui/button";

const IOPage = () => {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Giả lập đợi I/O</h2>
        <p className="text-muted-foreground">
          Giả lập độ trễ khi đọc/ghi Database hoặc File hệ thống.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <div className="p-4 border rounded-lg bg-card">
          <h3 className="font-semibold mb-2">DB Read Delay</h3>
          <p className="text-sm text-muted-foreground mb-4">
            Mô phỏng query chậm 2s
          </p>
          <Button className="w-full" variant="outline">
            Test Read
          </Button>
        </div>
        <div className="p-4 border rounded-lg bg-card">
          <h3 className="font-semibold mb-2">DB Write Delay</h3>
          <p className="text-sm text-muted-foreground mb-4">
            Mô phỏng transaction chậm 5s
          </p>
          <Button className="w-full" variant="outline">
            Test Write
          </Button>
        </div>
        <div className="p-4 border rounded-lg bg-card">
          <h3 className="font-semibold mb-2">File Upload</h3>
          <p className="text-sm text-muted-foreground mb-4">
            Mô phỏng ghi file lớn
          </p>
          <Button className="w-full" variant="outline">
            Test Upload
          </Button>
        </div>
      </div>
    </div>
  );
};

export default IOPage;
