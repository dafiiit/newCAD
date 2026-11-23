// Mock data for the NewCAD prototype, ported from the design canvas.
// Replace with engine responses once the API exists.
import type {
  CardType, Category, ChatThread, Commit, CommunityDesign, Concept, Connection, FollowUp, LibraryPart, MateType, QuestionInfo, Role, SettingsSection, Study, Version,
} from './types';

export const GENERIC_QS: string[] = [
  "What should this criterion capture?",
  "How will you judge whether it is met?",
  "Any hard limits?"
];

export const CATS: Category[] = [
  {
    "id": "function",
    "name": "Function",
    "qs": [
      "How precisely must it hold the generator on the shaft axis?",
      "What loads and vibration does it see at full flow?",
      "How is it fixed to the generator and the rig?"
    ]
  },
  {
    "id": "manufacturing",
    "name": "Manufacturing",
    "qs": [
      "Who builds the prototypes, with which tools?",
      "How many do you need on the rig, and by when?",
      "Which features need tight tolerances?"
    ]
  },
  {
    "id": "compatibility",
    "name": "Compatibility",
    "qs": [
      "What is around it on the rig that it must clear?",
      "Which bought-in parts must it accept?",
      "How is it installed and serviced on the rig?"
    ]
  },
  {
    "id": "looks",
    "name": "Looks",
    "qs": [
      "Will it be shown in demos, photos or papers?",
      "Which surface finish do you want?",
      "Should anything be marked on the part?"
    ]
  },
  {
    "id": "sustainability",
    "name": "Sustainability",
    "qs": [
      "What water is it in, and for how long?",
      "Which materials are allowed in that water?",
      "What happens to it after the test campaign?"
    ]
  }
];

export const PROPS: Record<Version, Concept> = {
  "1": {
    "name": "Concept A",
    "tag": "Plain welded L-bracket",
    "mass": "2.9 kg",
    "sf": "1.6",
    "stress": "148 MPa",
    "cost": "€38",
    "note": "Simplest to make. The upright root is the weak spot under vibration."
  },
  "2": {
    "name": "Concept B",
    "tag": "L-bracket with two gussets",
    "mass": "3.1 kg",
    "sf": "3.1",
    "stress": "77 MPa",
    "cost": "€44",
    "note": "Two gussets roughly halve peak stress at the upright root for a small cost increase.",
    "rec": true
  },
  "3": {
    "name": "Concept C",
    "tag": "Lightweight, thin plates with ribs",
    "mass": "2.2 kg",
    "sf": "2.2",
    "stress": "109 MPa",
    "cost": "€61",
    "note": "Lightest option. Thinner plates and two ribs, but more welding time."
  }
};

export const CONNS: Connection[] = [
  {
    "type": "fastened",
    "a": "upright",
    "b": "plate",
    "title": "Upright ⇄ Base plate",
    "how": {
      "1": "Fillet weld, both sides",
      "2": "Fillet weld + 2 gussets",
      "3": "Fillet weld + 2 ribs"
    }
  },
  {
    "type": "fastened",
    "a": "flange",
    "b": "upright",
    "title": "Generator flange ⇄ Upright",
    "how": {
      "1": "4 × M8 bolts",
      "2": "4 × M8 bolts",
      "3": "4 × M8 bolts"
    }
  },
  {
    "type": "revolute",
    "a": "gen",
    "b": "shaft",
    "title": "Generator ⇄ Shaft",
    "how": {
      "1": "Generator bearings (bought-in)",
      "2": "Generator bearings (bought-in)",
      "3": "Generator bearings (bought-in)"
    }
  },
  {
    "type": "fastened",
    "a": "shaft",
    "b": "hub",
    "title": "Shaft ⇄ Coupling hub",
    "how": {
      "1": "Keyed, set screw",
      "2": "Keyed, set screw",
      "3": "Keyed, set screw"
    }
  },
  {
    "type": "fastened",
    "a": "plate",
    "b": "bolts",
    "title": "Base plate ⇄ Rig frame",
    "how": {
      "1": "4 × M10 bolts",
      "2": "4 × M10 bolts",
      "3": "4 × M10 bolts"
    }
  }
];

export const MATE_TYPES: MateType[] = [
  {
    "id": "connector",
    "name": "Mate connector",
    "dof": null,
    "d": "M12 2v5M12 17v5M2 12h5M17 12h5M12 8.5a3.5 3.5 0 1 1 0 7a3.5 3.5 0 1 1 0-7z"
  },
  {
    "id": "fastened",
    "name": "Fastened",
    "dof": 0,
    "d": "M3 15h18v5H3zM8 6h8v9H8zM10.5 10.5h3"
  },
  {
    "id": "revolute",
    "name": "Revolute",
    "dof": 1,
    "d": "M3 17h18v4H3zM7 12.5a5 2 0 1 0 10 0a5 2 0 1 0-10 0zM12 12.5v4.5M4.5 8.5a7.5 3 0 0 1 15 0M17.2 5.6l2.3 2.9l-3.4.7"
  },
  {
    "id": "slider",
    "name": "Slider",
    "dof": 1,
    "d": "M3 16h18v4H3zM9 9h6v7H9zM2 6h5M4 4l-2 2l2 2M17 6h5M20 4l2 2l-2 2"
  },
  {
    "id": "cylindrical",
    "name": "Cylindrical",
    "dof": 2,
    "d": "M7 7v11M15 7v11M7 7a4 1.5 0 0 1 8 0a4 1.5 0 0 1-8 0zM7 18a4 1.5 0 0 0 8 0M20 4v16M18 6l2-2l2 2M18 18l2 2l2-2"
  },
  {
    "id": "planar",
    "name": "Planar",
    "dof": 3,
    "d": "M2 18l5-6h15l-5 6zM12 4v10M10 6l2-2l2 2M7 9h10M9 7l-2 2l2 2M15 7l2 2l-2 2"
  },
  {
    "id": "ball",
    "name": "Ball",
    "dof": 3,
    "d": "M12 4a6 6 0 1 1 0 12a6 6 0 1 1 0-12zM6 10a6 2 0 0 0 12 0M12 16v3M7 21h10"
  },
  {
    "id": "parallel",
    "name": "Parallel",
    "dof": 4,
    "d": "M4 20L12 4M12 20L20 4M3 12h3M14 12h3"
  }
];

export const BRANCH_COLORS: Record<string, string> = {
  "main": "#111111",
  "concept-b": "#1D4ED8",
  "concept-c": "#C2410C"
};

export const EXTRA_COLORS: string[] = [
  "#0F766E",
  "#7C3AED",
  "#B45309",
  "#BE185D"
];

export const SEED_COMMITS: Commit[] = [
  {
    "id": "a1f3",
    "branch": "main",
    "parents": [],
    "ver": 1,
    "msg": "Requirements imported from What?",
    "who": "Bot",
    "t": "09:02",
    "diff": "Read 5 criteria and 13 inputs. Created the base layout."
  },
  {
    "id": "b27c",
    "branch": "main",
    "parents": [
      "a1f3"
    ],
    "ver": 1,
    "msg": "Concept A: plain welded L-bracket",
    "who": "Bot",
    "t": "09:04",
    "diff": "+ base plate 10 mm, + upright 10 mm, fillet welds both sides"
  },
  {
    "id": "c90d",
    "branch": "concept-b",
    "parents": [
      "b27c"
    ],
    "ver": 2,
    "msg": "Add two gussets at the upright root",
    "who": "Bot",
    "t": "09:05",
    "diff": "+ 2 gussets 8 mm. Peak stress roughly halved."
  },
  {
    "id": "d4e2",
    "branch": "concept-c",
    "parents": [
      "b27c"
    ],
    "ver": 3,
    "msg": "Thin plates with two ribs",
    "who": "Bot",
    "t": "09:06",
    "diff": "plate 10 → 6 mm, upright 10 → 7 mm, + 2 ribs 5 mm"
  },
  {
    "id": "e518",
    "branch": "concept-b",
    "parents": [
      "c90d"
    ],
    "ver": 2,
    "msg": "Keep cable gland area free (comment 1)",
    "who": "You",
    "t": "09:12",
    "diff": "gussets moved outward to z = ±62 mm"
  },
  {
    "id": "f06a",
    "branch": "concept-c",
    "parents": [
      "d4e2"
    ],
    "ver": 3,
    "msg": "Lower rib height to 62 mm",
    "who": "Bot",
    "t": "09:14",
    "diff": "rib height 90 → 62 mm, mass −0.2 kg"
  },
  {
    "id": "9b11",
    "branch": "main",
    "parents": [
      "b27c",
      "e518"
    ],
    "ver": 2,
    "msg": "Merge concept-b: recommended design",
    "who": "You",
    "t": "09:20",
    "diff": "main now follows Concept B"
  }
];

export const QINFO: Record<string, QuestionInfo> = {
  "function:0": {
    "ask": "How precisely must the generator sit on the turbine shaft axis, and what may move?",
    "ex": [
      "Coaxial within ±0.2 mm, no tilt",
      "The coupling takes up to 1 mm offset",
      "Axial play is fine, no radial play"
    ],
    "assume": "Coaxial within ±0.2 mm; the jaw coupling takes small angular errors."
  },
  "function:1": {
    "ask": "What happens at full flow: speed, torque, vibration, shocks?",
    "ex": [
      "600 rpm, about 8 Nm, some imbalance",
      "Start-up jolts when the rotor catches",
      "Debris strikes on the duct"
    ],
    "assume": "4 kg overhung, 8 Nm reaction torque, 3 g vibration up to 15 Hz."
  },
  "function:2": {
    "ask": "Which interfaces are fixed already: flange, bolt pattern, rails?",
    "ex": [
      "Generator flange 4 × M8 on Ø100",
      "Rig rails with M10 T-nuts",
      "Reuse the old bracket holes"
    ],
    "assume": "4 × M8 on the generator flange, 4 × M10 into the rig rails."
  },
  "manufacturing:0": {
    "ask": "Who will build it, and which processes do they have?",
    "ex": [
      "Our workshop: MIG welding, drill press",
      "Order laser-cut parts online",
      "A local CNC shop"
    ],
    "assume": "Laser-cut plates ordered online, welded in your workshop."
  },
  "manufacturing:1": {
    "ask": "How many pieces, and when must the first one be on the rig?",
    "ex": [
      "3 before the next test in 3 weeks",
      "1 now, 2 after the first test",
      "5 for a field trial in spring"
    ],
    "assume": "3 prototypes within 3 weeks."
  },
  "manufacturing:2": {
    "ask": "Which features must be precise, and which can stay rough?",
    "ex": [
      "Shaft axis height ±0.2 mm",
      "Flange face flat after welding",
      "Only the bolt pattern"
    ],
    "assume": "Flange face machined after welding; everything else ISO 2768-m."
  },
  "compatibility:0": {
    "ask": "What is close by on the rig that it must clear or keep free?",
    "ex": [
      "Turbine duct 30 mm behind",
      "Cable exit on top of the generator",
      "Lifting eye must stay reachable"
    ],
    "assume": "20 mm clearance to the duct; cable exit and lifting eye stay free."
  },
  "compatibility:1": {
    "ask": "Which bought-in parts are fixed already?",
    "ex": [
      "500 W PM generator, flange Ø116",
      "Jaw coupling Ø16 / Ø20",
      "A4 stainless fasteners only"
    ],
    "assume": "Generator and jaw coupling from the part library, A4 fasteners."
  },
  "compatibility:2": {
    "ask": "How is it put on the rig, and what must be quick to swap?",
    "ex": [
      "Swap the generator without draining",
      "One person, working from above",
      "Re-fit without re-aligning"
    ],
    "assume": "One person swaps the generator from above, no re-alignment."
  },
  "looks:0": {
    "ask": "Will people outside the team see it?",
    "ex": [
      "Only the team sees it",
      "In investor demo videos",
      "At a trade fair stand"
    ],
    "assume": "Seen in demo videos: tidy, no styling."
  },
  "looks:1": {
    "ask": "Which finish do you want on the weldment?",
    "ex": [
      "Raw stainless, pickled",
      "Powder coat in our grey",
      "Bead blasted"
    ],
    "assume": "Pickled and passivated stainless."
  },
  "looks:2": {
    "ask": "Should anything be marked on the part?",
    "ex": [
      "Engraved part number",
      "Rotation direction arrow",
      "Lift point marked"
    ],
    "assume": "Engraved part number and rotation arrow."
  },
  "sustainability:0": {
    "ask": "What water is it in, and for how long at a time?",
    "ex": [
      "River water, months at a time",
      "Salt water, permanently",
      "Clean lab tank, a few days"
    ],
    "assume": "Fresh river water, submerged for months."
  },
  "sustainability:1": {
    "ask": "Which materials are allowed or banned in that water?",
    "ex": [
      "Stainless 316 only",
      "No zinc or copper coatings",
      "No paint that can flake off"
    ],
    "assume": "316L stainless, no coatings that can leach."
  },
  "sustainability:2": {
    "ask": "What should happen to it after the test campaign?",
    "ex": [
      "Reuse it on the next turbine size",
      "Keep the generator, scrap the rest",
      "Send it back for refurbishing"
    ],
    "assume": "Bolted, so the generator is reused and the steel recycled."
  }
};

export const GEN_CATS: Category[] = [
  {
    "id": "function",
    "name": "Function",
    "qs": [
      "What is the one job it must never fail at?",
      "Which loads, motions or forces act on it?",
      "What does it attach to or hold?"
    ]
  },
  {
    "id": "manufacturing",
    "name": "Manufacturing",
    "qs": [
      "How will it be made, and by whom?",
      "How many pieces, and by when?",
      "Which dimensions must be precise?"
    ]
  },
  {
    "id": "compatibility",
    "name": "Compatibility",
    "qs": [
      "What is around it that it must fit or clear?",
      "Which bought-in parts or standards are fixed?",
      "How is it assembled and serviced?"
    ]
  },
  {
    "id": "looks",
    "name": "Looks",
    "qs": [
      "Who will see it, and where?",
      "Which look and finish do you want?",
      "Any colours, logos or markings?"
    ]
  },
  {
    "id": "sustainability",
    "name": "Sustainability",
    "qs": [
      "Where will it be used: indoors, outdoors, wet, hot?",
      "Which materials are preferred or ruled out?",
      "What happens to it at end of life?"
    ]
  }
];

export const QINFO_GEN: Record<string, QuestionInfo> = {
  "function:0": {
    "ex": [
      "Hold the part steady while drilling",
      "Keep the sensor pointing level",
      "Carry 5 kg without bending"
    ],
    "assume": "Its main job as written in the overview."
  },
  "function:1": {
    "ex": [
      "Static, about 2 kg",
      "Shocks when it is dropped",
      "Constant vibration from a motor"
    ],
    "assume": "Static load from the overview, safety factor 2."
  },
  "function:2": {
    "ex": [
      "Two M6 screws into a wall",
      "Clamps onto a Ø30 tube",
      "Sits on a 40 mm profile"
    ],
    "assume": "Standard metric screws into the mounting surface."
  },
  "manufacturing:0": {
    "ex": [
      "3D printed at home (PLA/PETG)",
      "Laser-cut sheet metal, ordered online",
      "CNC milled aluminium"
    ],
    "assume": "3D printed in PETG for the first prototypes."
  },
  "manufacturing:1": {
    "ex": [
      "1 prototype this week",
      "10 pieces next month",
      "100+ later"
    ],
    "assume": "One prototype first, a small batch later."
  },
  "manufacturing:2": {
    "ex": [
      "Only the hole pattern",
      "A press fit for a bearing",
      "Nothing critical"
    ],
    "assume": "ISO 2768-m; holes ±0.1 mm."
  },
  "compatibility:0": {
    "ex": [
      "Must fit in a 100 mm gap",
      "Next to a hot motor",
      "Inside an existing housing"
    ],
    "assume": "Free space around it as in the overview."
  },
  "compatibility:1": {
    "ex": [
      "M6 screws only",
      "A 608 bearing",
      "Fits a GoPro mount"
    ],
    "assume": "ISO metric fasteners and common bought-in parts."
  },
  "compatibility:2": {
    "ex": [
      "One person, hand tools",
      "Tool-free, with clips",
      "Removable without damage"
    ],
    "assume": "One person with standard hand tools."
  },
  "looks:0": {
    "ex": [
      "Nobody, it is hidden",
      "Customers at the counter",
      "On camera in videos"
    ],
    "assume": "Mostly hidden; looks are low priority."
  },
  "looks:1": {
    "ex": [
      "Clean and industrial",
      "Rounded and friendly",
      "Minimal, hidden fasteners"
    ],
    "assume": "Plain and tidy, edges rounded."
  },
  "looks:2": {
    "ex": [
      "Black, matte",
      "Our brand colour",
      "Raw material is fine"
    ],
    "assume": "Raw material colour, no markings."
  },
  "sustainability:0": {
    "ex": [
      "Indoors, dry",
      "Outdoors, rain and UV",
      "Under water"
    ],
    "assume": "Indoors, room temperature, dry."
  },
  "sustainability:1": {
    "ex": [
      "Recyclable metals only",
      "No PVC",
      "Recycled plastic preferred"
    ],
    "assume": "Single-material where possible, easy to recycle."
  },
  "sustainability:2": {
    "ex": [
      "Easy to take apart",
      "Send it back for refurbishing",
      "Simply recycle it"
    ],
    "assume": "Screwed, not glued, so it can be taken apart."
  }
};

export const ONB_EXAMPLES: string[] = [
  "A wall mount for a 2 kg camera, outdoors",
  "A bracket that holds a NEMA 17 motor on a 40 mm profile",
  "A phone stand for my desk, 3D printed"
];

export const FOLLOWUPS: Record<string, FollowUp> = {
  "function:0": {
    "text": "Must the alignment hold under full load, or only when it is mounted?",
    "ex": [
      "Under full load",
      "Only at assembly",
      "Not sure"
    ],
    "assume": "Alignment must hold under full operating load."
  },
  "function:1": {
    "text": "Is there a worst case, like the rotor blocking or debris hitting it?",
    "ex": [
      "The rotor can block suddenly",
      "Debris hits the duct",
      "None that I know of"
    ],
    "assume": "Worst case: sudden rotor block, 3 × nominal torque."
  },
  "manufacturing:0": {
    "text": "Can your workshop weld stainless steel, or only mild steel?",
    "ex": [
      "Stainless TIG is fine",
      "Mild steel only",
      "We outsource welding"
    ],
    "assume": "Stainless TIG welding is available."
  },
  "compatibility:1": {
    "text": "Do you have the generator's STEP file or only a datasheet?",
    "ex": [
      "STEP file",
      "Only a datasheet",
      "Measure the real part"
    ],
    "assume": "Datasheet dimensions from the library part."
  },
  "sustainability:0": {
    "text": "Does the water carry sand or debris?",
    "ex": [
      "Yes, a sandy river",
      "No, clear water",
      "Not sure"
    ],
    "assume": "Some sand: avoid pockets where it can collect."
  }
};

export const FOLLOWUPS_GEN: Record<string, FollowUp> = {
  "function:0": {
    "text": "What happens if it fails: annoying, costly or dangerous?",
    "ex": [
      "Just annoying",
      "Costly downtime",
      "Someone could get hurt"
    ],
    "assume": "A failure is costly, not dangerous."
  },
  "function:1": {
    "text": "Is there a worst case, like a drop or a sudden shock?",
    "ex": [
      "Dropped from a table",
      "Hit by a tool",
      "Nothing special"
    ],
    "assume": "Survives a drop from 1 m."
  },
  "manufacturing:0": {
    "text": "Do you own the machine, or will you order the parts?",
    "ex": [
      "Own 3D printer",
      "Order online",
      "A local shop"
    ],
    "assume": "Parts are ordered online."
  },
  "sustainability:0": {
    "text": "Any temperatures beyond normal room conditions?",
    "ex": [
      "Up to 60 °C",
      "Below freezing",
      "No"
    ],
    "assume": "Between 0 and 40 °C."
  }
};

export const MORE_QS: Record<string, FollowUp> = {
  "function": {
    "text": "Should the generator position be adjustable later?",
    "ex": [
      "Yes, ±5 mm along the shaft",
      "No, fixed is fine",
      "Only with shims"
    ],
    "assume": "Fixed position, shims for fine alignment."
  },
  "manufacturing": {
    "text": "What may one prototype cost?",
    "ex": [
      "Under €50",
      "€50 to €150",
      "Does not matter yet"
    ],
    "assume": "Around €50 per piece."
  },
  "compatibility": {
    "text": "Do cables need to run through or along it?",
    "ex": [
      "Generator cable along the upright",
      "No cables",
      "A sensor cable as well"
    ],
    "assume": "Generator cable clipped along the upright."
  },
  "sustainability": {
    "text": "How is it cleaned after a test campaign?",
    "ex": [
      "Pressure washer",
      "By hand",
      "Not at all"
    ],
    "assume": "Rinsed with a pressure washer."
  }
};

export const MORE_QS_GEN: Record<string, FollowUp> = {
  "function": {
    "text": "Does it need to be adjustable after assembly?",
    "ex": [
      "Yes, a few millimetres",
      "No",
      "Not sure"
    ],
    "assume": "Not adjustable."
  },
  "manufacturing": {
    "text": "What may one piece cost?",
    "ex": [
      "Under €10",
      "€10 to €50",
      "Does not matter yet"
    ],
    "assume": "Low cost; prototype pricing."
  },
  "compatibility": {
    "text": "Do cables or hoses need to pass through or along it?",
    "ex": [
      "One cable",
      "No",
      "Several hoses"
    ],
    "assume": "No cables or hoses."
  },
  "sustainability": {
    "text": "How will it be cleaned or maintained?",
    "ex": [
      "Wiped by hand",
      "Not at all",
      "In a dishwasher"
    ],
    "assume": "Wiped by hand."
  }
};

export const NEEDS: Record<string, [CardType, string][]> = {
  "function:0": [
    [
      "sketch",
      "Sketch of the shaft line"
    ],
    [
      "model",
      "STEP of turbine and shaft"
    ]
  ],
  "function:1": [
    [
      "video",
      "Video of the rig at full flow"
    ],
    [
      "text",
      "Measured rpm or torque"
    ]
  ],
  "function:2": [
    [
      "image",
      "Photo of the mounting area"
    ],
    [
      "model",
      "STEP of the rig frame"
    ]
  ],
  "manufacturing:0": [
    [
      "image",
      "Photo of your workshop tools"
    ]
  ],
  "manufacturing:2": [
    [
      "sketch",
      "Mark the critical dimensions"
    ]
  ],
  "compatibility:0": [
    [
      "image",
      "Photo of the space on the rig"
    ],
    [
      "model",
      "STEP of the surroundings"
    ]
  ],
  "compatibility:1": [
    [
      "model",
      "STEP of the generator"
    ],
    [
      "image",
      "Datasheet or photo of the coupling"
    ]
  ],
  "compatibility:2": [
    [
      "video",
      "Short video of today’s assembly"
    ]
  ],
  "looks:1": [
    [
      "image",
      "Example of a finish you like"
    ]
  ],
  "sustainability:0": [
    [
      "image",
      "Photo of the water"
    ]
  ]
};

export const NEEDS_GEN: Record<string, [CardType, string][]> = {
  "function:0": [
    [
      "sketch",
      "A quick sketch of the idea"
    ]
  ],
  "function:2": [
    [
      "image",
      "Photo of where it attaches"
    ],
    [
      "model",
      "CAD of the mating part"
    ]
  ],
  "compatibility:0": [
    [
      "image",
      "Photo of the surroundings"
    ],
    [
      "model",
      "CAD of the surroundings"
    ]
  ],
  "compatibility:1": [
    [
      "model",
      "STEP of the bought-in parts"
    ]
  ],
  "looks:1": [
    [
      "image",
      "Examples you like"
    ]
  ]
};

export const NEED_ICON: Record<CardType, string> = {
  "model": "M12 3l8 4.5v9L12 21l-8-4.5v-9zM4 7.5l8 4.5 8-4.5M12 12v9",
  "image": "M3 4h18v16H3zM8.5 10a1.5 1.5 0 1 0 0-.01M21 16l-5-5-9 9",
  "video": "M3 6h13v12H3zM16 10l5-3v10l-5-3",
  "sketch": "M4 20l1.2-4.4L16.6 4.2a2 2 0 0 1 2.8 0l.4.4a2 2 0 0 1 0 2.8L8.4 18.8z",
  "text": "M4 6h16M4 12h16M4 18h10"
};

export const OVERVIEW_SEED: string = "A mount that holds a 4 kg generator coaxial with the shaft of our small hydrokinetic test turbine and carries its weight and vibration into the existing rig frame. It replaces the temporary bracket, has to survive months under water, and should be built as three welded prototypes for the next test campaign.";

export const OVERVIEW_FACTS: string[] = [
  "4 kg generator",
  "Coaxial with turbine shaft",
  "Under water for months",
  "Bolts to existing rig",
  "3 prototypes"
];

export const GENERIC_SUGG: string[] = [
  "Use the usual standard",
  "Keep it as simple as possible",
  "Not sure yet, propose options"
];

export const AHEAD_STAGES: [number, string][] = [
  [
    0,
    "Understanding your goal"
  ],
  [
    25,
    "Sketching first concepts"
  ],
  [
    45,
    "Sizing parts and connections"
  ],
  [
    65,
    "Running quick checks"
  ],
  [
    85,
    "Ranking proposals"
  ],
  [
    100,
    "Prototypes ready"
  ]
];

export const COMMUNITY: CommunityDesign[] = [
  {
    "id": "c1",
    "name": "Planetary gearbox 1:20",
    "author": "@ayla.makes",
    "tag": "Robotics",
    "kind": "gear",
    "likes": 412,
    "remixes": 58
  },
  {
    "id": "c2",
    "name": "E-bike battery wall mount",
    "author": "@marek_b",
    "tag": "Fixtures",
    "kind": "bracket",
    "likes": 236,
    "remixes": 31
  },
  {
    "id": "c3",
    "name": "River turbine nose cone",
    "author": "@hydrolab",
    "tag": "Energy",
    "kind": "turbine",
    "likes": 189,
    "remixes": 12
  },
  {
    "id": "c4",
    "name": "Quick-release desk clamp",
    "author": "@ola.design",
    "tag": "3D printing",
    "kind": "clamp",
    "likes": 527,
    "remixes": 96
  },
  {
    "id": "c5",
    "name": "Servo bracket, 3 sizes",
    "author": "@rbx",
    "tag": "Robotics",
    "kind": "bracket",
    "likes": 301,
    "remixes": 44
  },
  {
    "id": "c6",
    "name": "Small wind rotor hub",
    "author": "@windshed",
    "tag": "Energy",
    "kind": "turbine",
    "likes": 98,
    "remixes": 7
  }
];

export const CHAT_SEED: ChatThread[] = [
  {
    "id": "gm2",
    "project": "gm",
    "title": "Bolt clash in Concept B",
    "when": "Yesterday",
    "msgs": [
      {
        "who": "you",
        "text": "Interference check says a base bolt hits a gusset. Can you fix that?"
      },
      {
        "who": "bot",
        "text": "Yes. Moving the gussets 6 mm inward clears the bolt heads. Stress goes up by about 4 %. Shall I commit it on concept-b?"
      },
      {
        "who": "you",
        "text": "Do it."
      },
      {
        "who": "bot",
        "text": "Committed as a new version on concept-b. The clash is gone in the latest check."
      }
    ]
  },
  {
    "id": "gm3",
    "project": "gm",
    "title": "Vibration margin at 600 rpm",
    "when": "2 days ago",
    "msgs": [
      {
        "who": "you",
        "text": "Is the bracket safe if the rotor spins at 600 rpm?"
      },
      {
        "who": "bot",
        "text": "At 600 rpm the excitation is 10 Hz. Concept B has its first mode at 64 Hz, a 6.4× margin. That is comfortable."
      }
    ]
  },
  {
    "id": "sb1",
    "project": "sb",
    "title": "Mounting on DIN rail",
    "when": "Last week",
    "msgs": [
      {
        "who": "you",
        "text": "The sensor bracket should clip onto a 35 mm DIN rail."
      },
      {
        "who": "bot",
        "text": "Noted under Compatibility. I will use a standard TS35 clip profile and leave room for a screwdriver to release it."
      }
    ]
  },
  {
    "id": "sb2",
    "project": "sb",
    "title": "IP rating options",
    "when": "Last week",
    "msgs": [
      {
        "who": "you",
        "text": "What do I need for IP65?"
      },
      {
        "who": "bot",
        "text": "A sealed housing with a gasket and a cable gland. I can add both as requirements if you like."
      }
    ]
  },
  {
    "id": "gf1",
    "project": "gf",
    "title": "Soft vs rigid fingertips",
    "when": "3 weeks ago",
    "msgs": [
      {
        "who": "you",
        "text": "Should the gripper fingertips be soft?"
      },
      {
        "who": "bot",
        "text": "For mixed parts, a TPU pad on a rigid finger gives grip without losing precision. I prepared both on separate branches."
      }
    ]
  },
  {
    "id": "gf2",
    "project": "gf",
    "title": "Grip force check",
    "when": "3 weeks ago",
    "msgs": [
      {
        "who": "you",
        "text": "Can it hold 2 kg?"
      },
      {
        "who": "bot",
        "text": "With 40 N per finger and a friction coefficient of 0.6, yes, with a safety factor of about 2.4."
      }
    ]
  },
  {
    "id": "ph1",
    "project": "ph",
    "title": "Gasket groove dimensions",
    "when": "Last month",
    "msgs": [
      {
        "who": "you",
        "text": "Which groove size for a 3 mm O-ring?"
      },
      {
        "who": "bot",
        "text": "For a static face seal, about 2.3 mm deep and 4 mm wide. I will add it to the cover."
      }
    ]
  }
];

export const CHAT_PROJECTS: Record<string, string | null> = {
  "gm": null,
  "sb": "Sensor bracket",
  "gf": "Gripper finger",
  "ph": "Pump housing cover"
};

export const LIB_CATS: string[] = [
  "Fasteners",
  "Profiles & framing",
  "Bearings & shafts",
  "Motors & drives",
  "Gears & transmission",
  "Robots",
  "Community assemblies"
];

export const LIBRARY: LibraryPart[] = [
  {
    "id": "l1",
    "cat": "Fasteners",
    "name": "Socket head cap screw",
    "std": "ISO 4762",
    "icon": "bolt",
    "spec": "M3–M20, A2 / A4 / 8.8",
    "variants": [
      "M6 × 20",
      "M8 × 25",
      "M8 × 40",
      "M10 × 30",
      "M12 × 40"
    ],
    "material": "Stainless A4-70",
    "mass": "17 g (M8 × 25)",
    "source": "Standard part"
  },
  {
    "id": "l2",
    "cat": "Fasteners",
    "name": "Hex nut",
    "std": "ISO 4032",
    "icon": "nut",
    "spec": "M3–M24",
    "variants": [
      "M6",
      "M8",
      "M10",
      "M12"
    ],
    "material": "Steel 8, zinc plated",
    "mass": "5 g (M8)",
    "source": "Standard part"
  },
  {
    "id": "l3",
    "cat": "Fasteners",
    "name": "Flange bolt with serration",
    "std": "ISO 4162",
    "icon": "bolt",
    "spec": "Self-locking, M5–M12",
    "variants": [
      "M6 × 16",
      "M8 × 20",
      "M10 × 25"
    ],
    "material": "Steel 10.9",
    "mass": "14 g (M8 × 20)",
    "source": "Standard part"
  },
  {
    "id": "l4",
    "cat": "Fasteners",
    "name": "Threaded insert for plastics",
    "std": "Heat-set",
    "icon": "nut",
    "spec": "For 3D-printed parts",
    "variants": [
      "M3",
      "M4",
      "M5"
    ],
    "material": "Brass",
    "mass": "1 g",
    "source": "Standard part"
  },
  {
    "id": "l5",
    "cat": "Profiles & framing",
    "name": "Slot profile 40 × 40",
    "std": "Slot 8",
    "icon": "profile",
    "spec": "Aluminium, cut to length",
    "variants": [
      "200 mm",
      "500 mm",
      "1000 mm",
      "Custom length"
    ],
    "material": "Aluminium 6063-T6",
    "mass": "1.5 kg/m",
    "source": "Catalogue"
  },
  {
    "id": "l6",
    "cat": "Profiles & framing",
    "name": "Slot profile 40 × 80",
    "std": "Slot 8",
    "icon": "profile",
    "spec": "Aluminium, heavy duty",
    "variants": [
      "500 mm",
      "1000 mm",
      "Custom length"
    ],
    "material": "Aluminium 6063-T6",
    "mass": "2.7 kg/m",
    "source": "Catalogue"
  },
  {
    "id": "l7",
    "cat": "Profiles & framing",
    "name": "Angle bracket 40",
    "std": "Slot 8",
    "icon": "assembly",
    "spec": "With set screws",
    "variants": [
      "Standard",
      "Reinforced"
    ],
    "material": "Die-cast zinc",
    "mass": "60 g",
    "source": "Catalogue"
  },
  {
    "id": "l8",
    "cat": "Profiles & framing",
    "name": "T-slot nut",
    "std": "Slot 8",
    "icon": "nut",
    "spec": "Drop-in, spring loaded",
    "variants": [
      "M5",
      "M6",
      "M8"
    ],
    "material": "Steel, zinc plated",
    "mass": "6 g",
    "source": "Catalogue"
  },
  {
    "id": "l9",
    "cat": "Bearings & shafts",
    "name": "Deep groove ball bearing",
    "std": "ISO 15",
    "icon": "bearing",
    "spec": "6000 to 6210, 2RS sealed",
    "variants": [
      "6004-2RS (20 mm)",
      "6204-2RS (20 mm)",
      "6205-2RS (25 mm)"
    ],
    "material": "Bearing steel",
    "mass": "106 g (6204)",
    "source": "Standard part"
  },
  {
    "id": "l10",
    "cat": "Bearings & shafts",
    "name": "Pillow block bearing",
    "std": "UCP",
    "icon": "bearing",
    "spec": "Cast housing, set screws",
    "variants": [
      "UCP204 (20 mm)",
      "UCP205 (25 mm)"
    ],
    "material": "Cast iron housing",
    "mass": "0.7 kg",
    "source": "Catalogue"
  },
  {
    "id": "l11",
    "cat": "Bearings & shafts",
    "name": "Precision shaft",
    "std": "h6",
    "icon": "profile",
    "spec": "Hardened, ground",
    "variants": [
      "Ø12",
      "Ø16",
      "Ø20"
    ],
    "material": "Cf53, induction hardened",
    "mass": "1.6 kg/m (Ø16)",
    "source": "Catalogue"
  },
  {
    "id": "l12",
    "cat": "Motors & drives",
    "name": "Stepper motor NEMA 17",
    "std": "NEMA 17",
    "icon": "motor",
    "spec": "0.45 Nm, 1.8°",
    "variants": [
      "40 mm body",
      "48 mm body"
    ],
    "material": "—",
    "mass": "280 g",
    "source": "Catalogue"
  },
  {
    "id": "l13",
    "cat": "Motors & drives",
    "name": "BLDC servo 400 W",
    "std": "60 mm flange",
    "icon": "motor",
    "spec": "1.27 Nm, 3000 rpm",
    "variants": [
      "With brake",
      "Without brake"
    ],
    "material": "—",
    "mass": "1.2 kg",
    "source": "Catalogue"
  },
  {
    "id": "l14",
    "cat": "Motors & drives",
    "name": "Small generator 500 W",
    "std": "Flange Ø116",
    "icon": "motor",
    "spec": "Permanent magnet, 300 rpm",
    "variants": [
      "24 V",
      "48 V"
    ],
    "material": "—",
    "mass": "4 kg",
    "source": "Catalogue"
  },
  {
    "id": "l15",
    "cat": "Gears & transmission",
    "name": "Spur gear module 1",
    "std": "ISO 53",
    "icon": "gear",
    "spec": "12–80 teeth",
    "variants": [
      "z = 20",
      "z = 40",
      "z = 60"
    ],
    "material": "Steel C45",
    "mass": "45 g (z = 20)",
    "source": "Generated"
  },
  {
    "id": "l16",
    "cat": "Gears & transmission",
    "name": "Jaw coupling",
    "std": "Shaft Ø8–Ø25",
    "icon": "bearing",
    "spec": "Elastomer spider",
    "variants": [
      "Ø14/Ø14",
      "Ø16/Ø20",
      "Ø20/Ø25"
    ],
    "material": "Aluminium + TPU",
    "mass": "90 g",
    "source": "Catalogue"
  },
  {
    "id": "l17",
    "cat": "Robots",
    "name": "6-axis arm, 5 kg payload",
    "std": "ISO 9409 flange",
    "icon": "robot",
    "spec": "Reach 850 mm",
    "variants": [
      "Floor mount",
      "Ceiling mount"
    ],
    "material": "—",
    "mass": "24 kg",
    "source": "Vendor model"
  },
  {
    "id": "l18",
    "cat": "Robots",
    "name": "SCARA, 3 kg payload",
    "std": "ISO 9409 flange",
    "icon": "robot",
    "spec": "Reach 400 mm",
    "variants": [
      "Standard",
      "Clean room"
    ],
    "material": "—",
    "mass": "17 kg",
    "source": "Vendor model"
  },
  {
    "id": "l19",
    "cat": "Robots",
    "name": "Parallel gripper",
    "std": "ISO 9409-1-50",
    "icon": "assembly",
    "spec": "Stroke 2 × 20 mm, 140 N",
    "variants": [
      "Electric",
      "Pneumatic"
    ],
    "material": "—",
    "mass": "0.9 kg",
    "source": "Vendor model"
  },
  {
    "id": "l20",
    "cat": "Community assemblies",
    "name": "Planetary gearbox 1:20",
    "std": "@ayla.makes",
    "icon": "gear",
    "spec": "NEMA 17 input, printable",
    "variants": [
      "Latest version"
    ],
    "material": "PA12 + steel pins",
    "mass": "310 g",
    "source": "Community"
  },
  {
    "id": "l21",
    "cat": "Community assemblies",
    "name": "Servo bracket, 3 sizes",
    "std": "@rbx",
    "icon": "assembly",
    "spec": "Sheet metal",
    "variants": [
      "Small",
      "Medium",
      "Large"
    ],
    "material": "Steel 1.5 mm",
    "mass": "85 g",
    "source": "Community"
  },
  {
    "id": "l22",
    "cat": "Community assemblies",
    "name": "Quick-release desk clamp",
    "std": "@ola.design",
    "icon": "assembly",
    "spec": "For tubes Ø20–Ø40",
    "variants": [
      "Latest version"
    ],
    "material": "PETG",
    "mass": "120 g",
    "source": "Community"
  }
];

export const MODES: Record<Version, number[]> = {
  "1": [
    38,
    96,
    162
  ],
  "2": [
    64,
    141,
    233
  ],
  "3": [
    51,
    118,
    205
  ]
};

export const MODE_NAMES: string[] = [
  "Fore–aft bending",
  "Side sway",
  "Twist"
];

export const STUDIES: Study[] = [
  {
    "id": "static",
    "group": "Structural (FEM)",
    "icon": "FEM",
    "title": "Static stress",
    "sub": "Generator weight + 3 g vibration load",
    "engine": "FEM · linear static · tetra mesh 1.2 mm"
  },
  {
    "id": "modal",
    "group": "Vibration",
    "icon": "VIB",
    "title": "Natural frequencies",
    "sub": "Modes vs rotor speed",
    "engine": "FEM · modal · first 3 modes"
  },
  {
    "id": "vibration",
    "group": "Vibration",
    "icon": "VIB",
    "title": "Forced response",
    "sub": "Rotor imbalance swept 0–80 Hz",
    "engine": "FEM · harmonic response · 2 % damping"
  },
  {
    "id": "cfd",
    "group": "Fluid (CFD)",
    "icon": "CFD",
    "title": "Flow around the mount",
    "sub": "Drag and wake in a 1.5 m/s current",
    "engine": "CFD · RANS k-ω SST · 1.8 M cells"
  },
  {
    "id": "motion",
    "group": "Rigid bodies (MuJoCo)",
    "icon": "MJ",
    "title": "Rotor run-up",
    "sub": "Spin the shaft, check bearing loads",
    "engine": "MuJoCo · rigid bodies · 1 ms timestep · 10 s"
  },
  {
    "id": "soft",
    "group": "Soft & viscous bodies",
    "icon": "SB",
    "title": "Damper pads and water drag",
    "sub": "Rubber pads under the plate, viscous water",
    "engine": "MuJoCo flex · soft contacts · viscous damping"
  },
  {
    "id": "thermal",
    "group": "Heat",
    "icon": "TH",
    "title": "Heat transfer",
    "sub": "Generator heat into bracket and water",
    "engine": "FEM · steady-state thermal · water convection"
  }
];

export const ROLES: Role[] = [
  "Owner",
  "Editor",
  "Commenter",
  "Viewer"
];

export const AV_COLORS: string[] = [
  "#111111",
  "#1D4ED8",
  "#C2410C",
  "#0F766E",
  "#7C3AED",
  "#B45309"
];

export const SETTINGS_DEF: SettingsSection[] = [
  {
    "id": "account",
    "title": "Account",
    "intro": "How you appear to teammates and agents.",
    "rows": [
      {
        "key": "name",
        "label": "Display name",
        "help": "Shown on comments and versions.",
        "type": "text",
        "def": "You"
      },
      {
        "key": "email",
        "label": "Email",
        "help": "Used for invites and notifications.",
        "type": "text",
        "def": "you@example.com"
      },
      {
        "key": "lang",
        "label": "Language",
        "help": "Interface and Bot replies.",
        "type": "select",
        "opts": [
          "English",
          "Deutsch",
          "Français",
          "Español"
        ],
        "def": "English"
      },
      {
        "key": "hints",
        "label": "Show tool tips",
        "help": "Short hints at the top while a tool is active. Meant for getting started.",
        "type": "toggle",
        "def": false
      },
      {
        "key": "theme",
        "label": "Appearance",
        "help": "Dark is black with white lines. System follows your computer.",
        "type": "seg",
        "opts": [
          "Light",
          "Dark",
          "System"
        ],
        "def": "Light"
      }
    ]
  },
  {
    "id": "agent",
    "title": "Bot",
    "intro": "How much the agent does on its own.",
    "rows": [
      {
        "key": "autonomy",
        "label": "Autonomy",
        "help": "When Bot must ask you before changing the design.",
        "type": "seg",
        "opts": [
          "Ask every step",
          "Ask for big changes",
          "Autonomous"
        ],
        "def": "Ask for big changes"
      },
      {
        "key": "concepts",
        "label": "Concepts per request",
        "help": "How many alternatives to propose, each on its own branch.",
        "type": "select",
        "opts": [
          "1",
          "2",
          "3",
          "5"
        ],
        "def": "3"
      },
      {
        "key": "creativity",
        "label": "Exploration",
        "help": "Conservative stays close to known designs; exploratory tries unusual ones.",
        "type": "range",
        "min": 0,
        "max": 100,
        "step": 5,
        "def": 50,
        "fmt": "pct"
      },
      {
        "key": "autoSim",
        "label": "Run simulations automatically",
        "help": "Check every new version before showing it to you.",
        "type": "toggle",
        "def": true
      },
      {
        "key": "autoCommit",
        "label": "Commit agent changes",
        "help": "Every agent change becomes a version you can roll back.",
        "type": "toggle",
        "def": true
      },
      {
        "key": "explain",
        "label": "Explanations",
        "help": "Length of Bot replies.",
        "type": "seg",
        "opts": [
          "Short",
          "Detailed"
        ],
        "def": "Short"
      },
      {
        "key": "readComments",
        "label": "Read all comments",
        "help": "Treat 3D comments and sketches as change requests.",
        "type": "toggle",
        "def": true
      }
    ]
  },
  {
    "id": "units",
    "title": "Units & CAD",
    "intro": "Defaults for new projects.",
    "rows": [
      {
        "key": "units",
        "label": "Unit system",
        "help": "Lengths in the model and in dimensions.",
        "type": "seg",
        "opts": [
          "Metric (mm)",
          "Imperial (in)"
        ],
        "def": "Metric (mm)"
      },
      {
        "key": "angle",
        "label": "Angles",
        "help": "",
        "type": "seg",
        "opts": [
          "Degrees",
          "Radians"
        ],
        "def": "Degrees"
      },
      {
        "key": "material",
        "label": "Default material",
        "help": "Used until a requirement says otherwise.",
        "type": "select",
        "opts": [
          "S355 steel",
          "Aluminium 6082",
          "Stainless 1.4404",
          "PA12 (3D print)",
          "PLA"
        ],
        "def": "S355 steel"
      },
      {
        "key": "tolerance",
        "label": "General tolerance",
        "help": "Applied to dimensions without their own tolerance.",
        "type": "select",
        "opts": [
          "ISO 2768-f",
          "ISO 2768-m",
          "ISO 2768-c"
        ],
        "def": "ISO 2768-m"
      },
      {
        "key": "grid",
        "label": "Show floor grid",
        "help": "",
        "type": "toggle",
        "def": false
      },
      {
        "key": "orbit",
        "label": "Orbit sensitivity",
        "help": "How fast the model turns when you drag.",
        "type": "range",
        "min": 0.1,
        "max": 1,
        "step": 0.1,
        "def": 0.4,
        "fmt": "x"
      }
    ]
  },
  {
    "id": "sim",
    "title": "Simulation",
    "intro": "Defaults for structural checks.",
    "rows": [
      {
        "key": "solver",
        "label": "Solver quality",
        "help": "Accurate takes longer.",
        "type": "seg",
        "opts": [
          "Fast",
          "Balanced",
          "Accurate"
        ],
        "def": "Balanced"
      },
      {
        "key": "sfTarget",
        "label": "Target safety factor",
        "help": "Bot flags versions below this.",
        "type": "range",
        "min": 1,
        "max": 5,
        "step": 0.1,
        "def": 2,
        "fmt": "sf"
      },
      {
        "key": "vib",
        "label": "Include vibration",
        "help": "Adds a modal check to each run.",
        "type": "toggle",
        "def": true
      },
      {
        "key": "mesh",
        "label": "Show mesh",
        "help": "Overlay the simulation mesh on results.",
        "type": "toggle",
        "def": false
      }
    ]
  },
  {
    "id": "versions",
    "title": "Versions & branches",
    "intro": "How history works in your projects.",
    "rows": [
      {
        "key": "protectMain",
        "label": "Protect main",
        "help": "Merging into main needs a review by an Owner or Editor.",
        "type": "toggle",
        "def": true
      },
      {
        "key": "branchName",
        "label": "Branch naming",
        "help": "Pattern for branches Bot creates.",
        "type": "text",
        "def": "concept-{letter}"
      },
      {
        "key": "keep",
        "label": "Keep history",
        "help": "",
        "type": "select",
        "opts": [
          "Forever",
          "1 year",
          "90 days"
        ],
        "def": "Forever"
      }
    ]
  },
  {
    "id": "integrations",
    "title": "Integrations",
    "intro": "Bring files in and send designs out.",
    "rows": [
      {
        "key": "export",
        "label": "Default export format",
        "help": "",
        "type": "select",
        "opts": [
          "STEP AP242",
          "STEP AP214",
          "STL",
          "3MF",
          "Parasolid"
        ],
        "def": "STEP AP242"
      },
      {
        "key": "cOnshape",
        "label": "Onshape",
        "help": "Import parts and assemblies.",
        "type": "connect",
        "def": false
      },
      {
        "key": "cSolidworks",
        "label": "SolidWorks PDM",
        "help": "Sync released parts.",
        "type": "connect",
        "def": false
      },
      {
        "key": "cDrive",
        "label": "Google Drive",
        "help": "Pick images and videos for requirements.",
        "type": "connect",
        "def": true
      },
      {
        "key": "cGithub",
        "label": "GitHub",
        "help": "Mirror version history to a repository.",
        "type": "connect",
        "def": false
      }
    ]
  },
  {
    "id": "notifications",
    "title": "Notifications",
    "intro": "What reaches you outside the app.",
    "rows": [
      {
        "key": "nRun",
        "label": "Bot finished a run",
        "help": "",
        "type": "toggle",
        "def": true
      },
      {
        "key": "nComment",
        "label": "New comments on my projects",
        "help": "",
        "type": "toggle",
        "def": true
      },
      {
        "key": "nReview",
        "label": "Review requested",
        "help": "Someone wants to merge into main.",
        "type": "toggle",
        "def": true
      },
      {
        "key": "nWeekly",
        "label": "Weekly summary email",
        "help": "",
        "type": "toggle",
        "def": false
      }
    ]
  }
];

