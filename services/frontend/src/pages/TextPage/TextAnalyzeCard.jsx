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
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { FileText, HelpCircle } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

const TextAnalyzeCard = () => {
  const [text, setText] = useState("");
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);

  const handleAnalyze = async () => {
    if (!text) {
      toast.error("Please enter a bit more text");
      return;
    }

    try {
      setLoading(true);
      setResult(null);

      const response = await textApi.analyzeText(text);
      setResult(response.data);
    } catch (err) {
      toast.error("Failed to analyze text");
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
          <FileText className="w-5 h-5 text-blue-500" />
          <CardTitle>Text analysis</CardTitle>
        </div>
        <CardDescription>
          Analyze length, vocabulary, and term frequency.
        </CardDescription>
      </CardHeader>

      <CardContent className="flex flex-1 flex-col gap-4">
        <div className="space-y-2">
          <Label>Input text</Label>
          <Textarea
            placeholder="Paste any text here..."
            value={text}
            onChange={(e) => setText(e.target.value)}
            disabled={loading}
            rows={4}
          />
        </div>

        <div className="flex min-h-[10rem] flex-1 flex-col rounded-md bg-muted/50 p-3 text-sm">
          {result === null ? (
            <div className="flex h-full flex-1 items-center justify-center gap-2 text-center text-muted-foreground">
              <HelpCircle className="w-4 h-4" />
              No results yet
            </div>
          ) : (
            <div className="space-y-2 animate-in fade-in zoom-in duration-300">
              <div>
                📏 Characters: <b>{result.analysis.length}</b>
              </div>
              <div>
                🧩 Words: <b>{result.analysis.totalWords}</b>
              </div>
              <div>
                📘 Unique words: <b>{result.analysis.uniqueWords}</b>
              </div>
              <div>
                ⏱ Processing time: <b>{result.timeTaken}</b>
              </div>

              <div className="pt-2 border-t">
                <p className="font-semibold mb-1">Most frequent words:</p>
                <ul className="text-xs space-y-1">
                  {result.analysis.topWords.map((w) => (
                    <li key={w.word}>
                      • {w.word} ({w.count})
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          )}
        </div>
      </CardContent>

      <CardFooter>
        <Button
          className="w-full"
          variant="outline"
          onClick={handleAnalyze}
          disabled={loading}
        >
          {loading ? "Analyzing..." : "Analyze"}
        </Button>
      </CardFooter>
    </Card>
  );
};

export default TextAnalyzeCard;
