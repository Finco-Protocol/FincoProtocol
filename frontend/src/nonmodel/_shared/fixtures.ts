export type Instrument = {
  id: string; symbol: string; name: string; category: string; venue: string; chain: string;
  instrumentId: string; contract: string; representation: string; market: number | null; reference: number | null;
  marketAt: string; referenceAt: string; marketStatus: "AVAILABLE" | "STALE" | "UNAVAILABLE";
  referenceStatus: "AVAILABLE" | "STALE" | "UNAVAILABLE"; skewSec: number; unit: string;
};

export const DEMO_CLOCK_ISO = "2026-10-21T14:32:30.000Z";
export const DEMO_CLOCK_LABEL = "21 OCT 2026 · 14:32:30 UTC · FROZEN DEMO CLOCK";

export const instruments: Instrument[] = [
  { id:"fx-demo-001",symbol:"xTSLA",name:"Tesla equity representation",category:"Stocks",venue:"Demo venue / Northstar",chain:"Ethereum · Sepolia",instrumentId:"finco:demo:equity:TSLA:001",contract:"fixture://finco/demo/ethereum-sepolia/erc20/TSLA-001 · NOT DEPLOYED",representation:"Synthetic ERC-20 wrapper; not an issuer-backed claim",market:247.82,reference:249.16,marketAt:"2026-10-21T14:32:06Z",referenceAt:"2026-10-21T14:31:18Z",marketStatus:"AVAILABLE",referenceStatus:"AVAILABLE",skewSec:48,unit:"USD" },
  { id:"fx-demo-002",symbol:"xNVDA",name:"NVIDIA equity representation",category:"Stocks",venue:"Demo venue / Northstar",chain:"Arbitrum Sepolia",instrumentId:"finco:demo:equity:NVDA:002",contract:"fixture://finco/demo/arbitrum-sepolia/erc20/NVDA-002 · NOT DEPLOYED",representation:"Synthetic ERC-20 wrapper; not an issuer-backed claim",market:139.40,reference:141.02,marketAt:"2026-10-21T14:26:02Z",referenceAt:"2026-10-21T14:16:01Z",marketStatus:"AVAILABLE",referenceStatus:"STALE",skewSec:601,unit:"USD" },
  { id:"fx-demo-003",symbol:"BTC",name:"Bitcoin spot reference",category:"Crypto",venue:"Demo venue / Meridian",chain:"Bitcoin · reference only",instrumentId:"finco:demo:crypto:BTC:003",contract:"fixture://finco/demo/native-reference/BTC-003 · NO CONTRACT",representation:"Native asset reference; no tokenized representation",market:67214.50,reference:66891.22,marketAt:"2026-10-21T14:31:40Z",referenceAt:"2026-10-21T14:31:12Z",marketStatus:"AVAILABLE",referenceStatus:"AVAILABLE",skewSec:28,unit:"USD" },
  { id:"fx-demo-004",symbol:"ETH",name:"Ether spot reference",category:"Crypto",venue:"Demo venue / Meridian",chain:"Ethereum · reference only",instrumentId:"finco:demo:crypto:ETH:004",contract:"fixture://finco/demo/native-reference/ETH-004 · NO CONTRACT",representation:"Native asset reference; no tokenized representation",market:2634.18,reference:2640.70,marketAt:"2026-10-21T14:30:51Z",referenceAt:"2026-10-21T14:30:22Z",marketStatus:"AVAILABLE",referenceStatus:"AVAILABLE",skewSec:29,unit:"USD" },
  { id:"fx-demo-005",symbol:"USDG",name:"Paxos Global Dollar",category:"Stablecoins",venue:"Demo venue / Northstar",chain:"Ethereum · Sepolia",instrumentId:"finco:demo:stablecoin:USDG:005",contract:"fixture://finco/demo/ethereum-sepolia/erc20/USDG-005 · NOT DEPLOYED",representation:"USDG identity shown as issued; USD peg not assumed",market:1.001,reference:1.000,marketAt:"2026-10-21T14:29:50Z",referenceAt:"2026-10-21T14:24:05Z",marketStatus:"AVAILABLE",referenceStatus:"STALE",skewSec:345,unit:"USD" },
  { id:"fx-demo-006",symbol:"xGLD",name:"Tokenized gold reference",category:"Tokenized Markets",venue:"No venue observation",chain:"Ethereum · Sepolia",instrumentId:"finco:demo:commodity:XAU:006",contract:"fixture://finco/demo/ethereum-sepolia/XAU-006 · UNASSIGNED",representation:"Unverified synthetic identity; no verified contract",market:null,reference:2731.60,marketAt:"Unavailable",referenceAt:"2026-10-21T13:51:00Z",marketStatus:"UNAVAILABLE",referenceStatus:"STALE",skewSec:2500,unit:"USD/oz" },
];

export const sourceDocs = [
  ["Product truth · Crypto terminal","docs/CRYPTO_TERMINAL_PRODUCT_TRUTH.md","Access states, visual boundaries and feature truth."],
  ["Radar V1 release limitations","docs/radar/RADAR_V1_RELEASE_LIMITATIONS.md","Release state and operational limitations."],
  ["R-LIVE V2 admission","docs/radar/r_live_v2_admission.md","Admission rules and freshness policy."],
  ["Tokenized Monitor V2","docs/radar/R4_TOKENIZED_MONITOR_V2.md","R4 draft feature candidate."],
  ["Signal lifecycle V1","docs/radar/R5_TOKENIZED_SIGNAL_LIFECYCLE_V1.md","Future authorized consumer library."],
  ["Signal feed V1","docs/radar/R6_TOKENIZED_SIGNAL_FEED_V1.md","Draft candidate; independent approval required."],
  ["Roadmap","docs/ROADMAP.md","Stages and delivery targets."],
  ["Protocol navigation partial","app/templates/partials/_protocol_nav.html","Protocol information architecture reference."],
  ["Radar domain navigation","app/templates/radar/domain_nav.html","Radar navigation source."],
  ["Design tokens","static/tokens.css","Existing token reference."],
  ["Radar styles","static/radar/radar.css","Existing Radar visual reference."],
];
export const githubDoc = (path: string) => `https://github.com/Finco-Protocol/FincoProtocol/blob/main/${path}`;
