import ioApi from "@/api/IOApi";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Download, HelpCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

const IOReadCard = () => {
  const [fileId, setFileId] = useState("slot-0");
  const [sizeKb, setSizeKb] = useState(256);
  const [holdMs, setHoldMs] = useState(10);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleRead = async () => {
    try {
      setLoading(true);
      setResult(null);

      const response = await ioApi.readFile({ fileId, sizeKb, holdMs });
      setResult(response.data);
    } catch (error) {
      toast.error("Failed to read the workload file");
      console.error(error);
    } finally {
      setLoading(false);
    }
  };

  return (
    <Card className="flex flex-col relative h-full">
      {loading && (
        <div className="absolute inset-0 bg-background/50 backdrop-blur-sm z-50 flex items-center justify-center rounded-lg">
          <span className="animate-spin text-primary text-2xl">⏳</span>
        </div>
      )}

      <CardHeader>
        <div className="flex items-center gap-2">
          <Download className="w-5 h-5 text-sky-500" />
          <CardTitle>File read</CardTitle>
        </div>
        <CardDescription>
          Read a seeded file from the mounted volume to simulate file I/O read.
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-4">
        <div className="grid grid-cols-1 gap-3 md:hidden">
          <div className="space-y-2">
            <Label htmlFor="file-id-mobile">File ID</Label>
            <Input
              id="file-id-mobile"
              value={fileId}
              onChange={(e) => setFileId(e.target.value)}
              disabled={loading}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="size-kib-mobile">Size (KiB)</Label>
            <Input
              id="size-kib-mobile"
              type="number"
              value={sizeKb}
              onChange={(e) => setSizeKb(Number(e.target.value))}
              disabled={loading}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="hold-time-mobile">Hold time (ms)</Label>
            <Input
              id="hold-time-mobile"
              type="number"
              value={holdMs}
              onChange={(e) => setHoldMs(Number(e.target.value))}
              disabled={loading}
            />
          </div>
        </div>

        <div className="hidden gap-2 md:grid md:grid-cols-3">
          <Label htmlFor="file-id" className="leading-snug">
            File ID
          </Label>
          <Label htmlFor="size-kib" className="leading-snug">
            Size (KiB)
          </Label>
          <Label htmlFor="hold-time" className="leading-snug">
            Hold time (ms)
          </Label>
          <Input
            id="file-id"
            value={fileId}
            onChange={(e) => setFileId(e.target.value)}
            disabled={loading}
          />
          <Input
            id="size-kib"
            type="number"
            value={sizeKb}
            onChange={(e) => setSizeKb(Number(e.target.value))}
            disabled={loading}
          />
          <Input
            id="hold-time"
            type="number"
            value={holdMs}
            onChange={(e) => setHoldMs(Number(e.target.value))}
            disabled={loading}
          />
        </div>

        <div className="flex min-h-[10rem] flex-1 flex-col rounded-md bg-muted/50 p-3 text-sm">
          {result === null ? (
            <div className="flex h-full flex-1 items-center justify-center gap-2 text-center text-muted-foreground">
              <HelpCircle className="w-4 h-4" /> No results yet
            </div>
          ) : (
            <div className="space-y-2 animate-in fade-in zoom-in duration-300">
              <div>
                Bytes read: <b>{result.bytesRead.toLocaleString()}</b>
              </div>
              <div>
                Storage key: <b>{result.storageKey}</b>
              </div>
              <div>
                Checksum: <b>{result.checksum}</b>
              </div>
              <div>
                Processing time: <b>{result.timeTaken}</b>
              </div>
            </div>
          )}
        </div>
      </CardContent>

      <CardFooter>
        <Button
          className="w-full"
          variant="outline"
          onClick={handleRead}
          disabled={loading}
        >
          {loading ? "Reading..." : "Run read test"}
        </Button>
      </CardFooter>
    </Card>
  );
};

export default IOReadCard;
