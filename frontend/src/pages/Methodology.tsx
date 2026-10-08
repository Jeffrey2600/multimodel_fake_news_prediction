import { VERDICT } from '../verdicts'

export default function Methodology() {
  return (
    <div className="prose">
      <h1 className="page-title">How TruthLens checks a claim</h1>
      <p className="page-lede">
        A verdict is only as good as the evidence behind it. Here is exactly what happens between pressing
        “Check” and seeing a result, and how much to trust it.
      </p>

      <h2>The process</h2>
      <ol className="flow">
        <li>
          <b>Read the input</b>
          Text is cleaned and normalised. Links are fetched and the article body, headline, publisher and date are
          extracted. Images and scanned PDFs are read with OCR; Word and text PDFs are parsed directly. Voice
          recordings are transcribed by a dedicated speech-to-text model (Gemini transcription, or Whisper running
          locally as a fallback); videos have their audio transcribed and frames sampled every few seconds for
          on-screen text. The transcript is always shown on the report so you can check it.
        </li>
        <li>
          <b>Extract the claims</b>
          A language model splits the content into up to five atomic, self-contained factual claims, keeping names,
          dates, places and numbers exactly as stated, and marks the ones the content is mainly about. Opinions and
          questions are skipped.
        </li>
        <li>
          <b>Gather evidence</b>
          For every claim, several searches run in parallel across web and news search, Wikipedia, NewsAPI (when
          configured) and Google Search grounding (when the account has quota). The best results are opened and the
          passages that discuss the claim are kept. Duplicate articles are removed.
        </li>
        <li>
          <b>Compare claims with sources</b>
          Gemini reads each claim against every retrieved source and labels each one as supporting, contradicting or
          background, noting the decisive passage and any wrong detail (date, number, person, place).
        </li>
        <li>
          <b>Reach a verdict</b>
          The verification engine weighs the labelled evidence by source quality, relevance and independence (one
          vote per publisher), checks that the model’s verdict agrees with the evidence balance, and calibrates the
          confidence. Claim verdicts are then combined into the overall verdict, giving most weight to the central
          claims.
        </li>
      </ol>

      <h2>What the verdicts mean</h2>
      <div className="verdict-defs">
        {(['Supported', 'Mixed', 'Contradicted', 'Insufficient'] as const).map((v) => (
          <div key={v} className={`t-${VERDICT[v].tone}`}>
            <b>
              {VERDICT[v].icon} {VERDICT[v].label}
            </b>
            {VERDICT[v].line}
          </div>
        ))}
      </div>
      <p>
        <b>Can’t confirm</b> doesn’t mean “probably fake”. It means the evidence available right now can’t settle the
        question, which is common for very recent or private events.
      </p>

      <h2>How sources are weighted</h2>
      <p>Each source’s vote is multiplied by its type and by how directly it addresses the claim.</p>
      <table className="weights">
        <tbody>
          <tr><td>Government, courts, science agencies, UN bodies</td><td>1.00</td></tr>
          <tr><td>Fact-checkers (AFP, Reuters Fact Check, Alt News, BOOM, PolitiFact…)</td><td>0.95</td></tr>
          <tr><td>News agencies (Reuters, AP, PTI…)</td><td>0.95</td></tr>
          <tr><td>Established newsrooms</td><td>0.85</td></tr>
          <tr><td>Encyclopedias, journals, universities</td><td>0.75</td></tr>
          <tr><td>Other sites</td><td>0.50</td></tr>
          <tr><td>Social media posts</td><td>0.25</td></tr>
          <tr><td>Known fabricators and satire</td><td>0.10</td></tr>
        </tbody>
      </table>
      <p>
        Confidence reflects both the model’s certainty and the weight of agreeing evidence: a verdict with no backing
        sources is capped at 70%, and one that the evidence balance disagrees with is capped at 60%.
      </p>

      <h2>Context, bias and missing information</h2>
      <p>
        Separately from the verdict, every report notes how the content is framed: loaded or emotive language, one-sided
        sourcing, cherry-picked numbers, missing dates or attributions, and satire. A claim can be factually accurate and
        still misleading.
      </p>

      <h2>When the AI service is down</h2>
      <p>
        If every Gemini model is rate-limited or unavailable, TruthLens automatically falls back to an offline engine:
        claims are split heuristically and each source passage is scored by a local natural-language-inference model
        (DeBERTa-v3, trained on MNLI, FEVER and ANLI). These results are marked on the report as indicative.
      </p>

      <h2>Privacy</h2>
      <p>
        Uploaded files are processed in memory or in a temporary folder that is deleted as soon as the text is
        extracted. Only the extracted text, claims, sources and verdict are stored, in your history, which you can
        delete at any time. Text is sent to Google’s Gemini API for analysis.
      </p>

      <h2>Limits</h2>
      <ul>
        <li>Events from the last few hours may not be covered by any source yet.</li>
        <li>Search results can be dominated by a viral false story; the verdict is only as good as what was found.</li>
        <li>The tool reads text. It does not detect edited photos or deepfake video.</li>
        <li>Always open the sources for anything important.</li>
      </ul>
    </div>
  )
}
