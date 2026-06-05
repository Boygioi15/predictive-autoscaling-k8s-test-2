import textApi from "@/api/textApi";
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
import { HelpCircle, Repeat } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

const TextTransformCard = () => {
  const [text, setText] = useState("");
  const [rounds, setRounds] = useState(50);
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleTransform = async () => {
    if (!text || text.length === 0) {
      toast.error("Please enter text");
      return;
    }

    try {
      setLoading(true);
      setResult(null);

      const response = await textApi.transformText(text, rounds);
      setResult(response.data);
    } catch (err) {
      toast.error("Failed to transform text");
      console.error(err);
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
          <Repeat className="w-5 h-5 text-purple-500" />
          <CardTitle>Text transformation</CardTitle>
        </div>
        <CardDescription>
          Reverse the string and process it for multiple rounds to create CPU
          load.
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-4">
        <div className="space-y-2">
          <Label>Text</Label>
          <Input
            placeholder="e.g. Hello World"
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={loading}
          />
        </div>

        <div className="space-y-2">
          <Label>Processing rounds</Label>
          <Input
            type="number"
            value={rounds}
            onChange={(e) => setRounds(Number(e.target.value))}
            disabled={loading}
          />
        </div>

        <div className="flex min-h-[8rem] flex-1 flex-col rounded-md bg-muted/50 p-3 text-sm">
          {result === null ? (
            <div className="flex h-full flex-1 items-center justify-center gap-2 text-center text-muted-foreground">
              <HelpCircle className="w-4 h-4" /> No results yet
            </div>
          ) : (
            <div className="animate-in fade-in zoom-in duration-300 space-y-1">
              <div>
                📏 Input length: <b>{result.originalLength}</b>
              </div>
              <div>
                🔁 Rounds: <b>{result.rounds}</b>
              </div>
              <div>
                ⏱ Processing time: <b>{result.timeTaken}</b>
              </div>
            </div>
          )}
        </div>
      </CardContent>

      <CardFooter>
        <Button
          className="w-full"
          variant="outline"
          onClick={handleTransform}
          disabled={loading}
        >
          {loading ? "Processing..." : "Run transformation"}
        </Button>
      </CardFooter>
    </Card>
  );
};
export default TextTransformCard;
