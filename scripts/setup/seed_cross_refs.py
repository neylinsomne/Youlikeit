"""Seed cross-references for Berserk across all 3 personas."""
import sqlite3
import sys

conn = sqlite3.connect(sys.argv[1] if len(sys.argv) > 1 else "data/shorts_pipeline.db")

conn.executescript("""
CREATE TABLE IF NOT EXISTS cross_references (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_work TEXT NOT NULL,
    source_type TEXT NOT NULL,
    target_work TEXT NOT NULL,
    target_type TEXT NOT NULL,
    target_creator TEXT,
    reference_type TEXT NOT NULL,
    description_deep_mind TEXT,
    description_cinephile TEXT,
    description_pop_oracle TEXT,
    themes TEXT,
    strength REAL DEFAULT 0.7,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
""")

# Clear existing
conn.execute("DELETE FROM cross_references WHERE source_work = 'Berserk'")

refs = [
    # --- MOVIES ---
    {
        "target": "Macbeth", "type": "movie", "creator": "Shakespeare/Polanski",
        "ref_type": "thematic", "strength": 0.95,
        "themes": "ambition,betrayal,power,sacrifice",
        "deep_mind": "Griffith is Macbeth reborn. Ambition that devours the soul. Both trade love for power, and both discover the crown weighs nothing when you have no one left.",
        "cinephile": "Polanski frames Macbeth the same way Miura frames Griffith. Close-ups during the betrayal, wide shots for the aftermath. The craft of showing a man becoming a monster.",
        "pop_oracle": "Griffith did a Macbeth speedrun. Lady Macbeth at least had guilt. Griffith just floated away like nothing happened. Main character energy gone wrong.",
    },
    {
        "target": "Apocalypse Now", "type": "movie", "creator": "Francis Ford Coppola",
        "ref_type": "thematic", "strength": 0.9,
        "themes": "darkness,madness,power,moral_collapse",
        "deep_mind": "The Eclipse is Berserk's river into darkness. Like Kurtz, Griffith transcends morality, not through madness, but through absolute clarity. The horror is that he chose this.",
        "cinephile": "Coppola used Vietnam's jungle as Miura uses the Eclipse void. Both are spaces where civilization's rules dissolve. The cinematography of moral collapse.",
        "pop_oracle": "Colonel Kurtz and Griffith would be besties. Both went to the dark side and said 'actually, it's better here.' At least Kurtz had the decency to stay in the jungle.",
    },
    {
        "target": "2001: A Space Odyssey", "type": "movie", "creator": "Stanley Kubrick",
        "ref_type": "craft", "strength": 0.85,
        "themes": "transcendence,evolution,cosmic_horror",
        "deep_mind": "Miura and Kubrick share an obsession: the moment a being transcends its nature. The monolith transforms apes into humans. The Behelit transforms Griffith into God Hand. Both are silent, cosmic, terrifying.",
        "cinephile": "Kubrick's Stargate sequence and Miura's Eclipse share DNA. Both shatter visual conventions to show transcendence. Kubrick used slit-scan photography, Miura used double-page spreads that break panel borders.",
        "pop_oracle": "The Eclipse is basically the Stargate scene but with more screaming. Kubrick made it trippy, Miura made it traumatic. Same energy, different nightmares.",
    },
    {
        "target": "The Godfather", "type": "movie", "creator": "Francis Ford Coppola",
        "ref_type": "thematic", "strength": 0.9,
        "themes": "transformation,sacrifice,power,family",
        "deep_mind": "Griffith and Michael Corleone walk the same path. The transformation of an idealist into a monster. Both believe they sacrifice for a greater purpose. Both are lying to themselves.",
        "cinephile": "Coppola's baptism montage where Michael becomes Don is structurally identical to the Eclipse. Cutting between sacred ritual and profane violence. The craft of juxtaposition as moral commentary.",
        "pop_oracle": "Griffith is Michael Corleone if Michael had a Behelit instead of a family business. Same 'I did it for us' energy, same everyone-around-me-dies outcome.",
    },
    {
        "target": "Blade Runner", "type": "movie", "creator": "Ridley Scott",
        "ref_type": "thematic", "strength": 0.8,
        "themes": "existence,meaning,persistence,beauty_in_darkness",
        "deep_mind": "Roy Batty's 'tears in rain' and Guts' survival share the same question: what makes a life worth living when the universe is indifferent? Both find the answer in the act of persisting.",
        "cinephile": "Scott's rain-soaked neon and Miura's cross-hatched darkness create the same atmosphere. Worlds where beauty exists alongside horror, and the camera never looks away from either.",
        "pop_oracle": "Guts is basically Roy Batty but he refuses to die in the rain. Same tragic backstory energy, same 'I've seen things you wouldn't believe' vibes.",
    },
    # --- SERIES ---
    {
        "target": "Game of Thrones", "type": "series", "creator": "George R.R. Martin",
        "ref_type": "thematic", "strength": 0.85,
        "themes": "betrayal,massacre,trust,shock",
        "deep_mind": "The Red Wedding and the Eclipse serve the same narrative function. The brutal reminder that hope is a weapon wielded by storytellers against their audience.",
        "cinephile": "Both Miura and Martin understood that shocking violence only works when you've earned the audience's trust first. Years of character building for one devastating payoff.",
        "pop_oracle": "The Red Wedding wishes it was the Eclipse. Berserk did 'everyone dies at a party' twenty years before Game of Thrones and did it ten times harder.",
    },
    {
        "target": "Breaking Bad", "type": "series", "creator": "Vince Gilligan",
        "ref_type": "thematic", "strength": 0.8,
        "themes": "descent,transformation,ego,consequences",
        "deep_mind": "Walter White and Griffith demonstrate the same truth: the line between ambition and evil is not a line at all. It is a slope, and gravity does the rest.",
        "cinephile": "Gilligan and Miura both mastered the slow transformation. Each scene, each panel, adds one more shade of grey until the character is unrecognizable.",
        "pop_oracle": "Walter White is Griffith with a chemistry degree. 'I am the one who knocks' is basically 'I sacrifice' but with more meth.",
    },
    # --- MANGA/ANIME ---
    {
        "target": "Vinland Saga", "type": "manga", "creator": "Makoto Yukimura",
        "ref_type": "thematic", "strength": 0.85,
        "themes": "violence,redemption,growth,warrior",
        "deep_mind": "Thorfinn and Guts are mirror images. Both forged in violence, both seeking something beyond it. But where Guts clings to rage as survival, Thorfinn discovers that true strength is letting go.",
        "cinephile": "Yukimura studied Miura's work closely. You can see it in the battle choreography. But where Miura's panels compress violence into intensity, Yukimura's expand it into duration.",
        "pop_oracle": "Thorfinn is what happens when Guts goes to therapy. Same angry Viking energy but one of them actually grows as a person.",
    },
    {
        "target": "Neon Genesis Evangelion", "type": "anime", "creator": "Hideaki Anno",
        "ref_type": "thematic", "strength": 0.9,
        "themes": "trauma,abandonment,deconstruction,duty",
        "deep_mind": "Both Evangelion and Berserk ask: what happens when the person chosen to save the world doesn't want to be saved themselves? Shinji and Guts carry the same wound.",
        "cinephile": "Anno and Miura both deconstructed their genres in the mid-90s. Evangelion broke mecha, Berserk broke fantasy. Both used extreme violence as a mirror for psychological trauma.",
        "pop_oracle": "Shinji and Guts both have daddy issues that could fill an entire season of Dr. Phil. Get in the robot, Shinji. Grab the sword, Guts. Same energy.",
    },
    {
        "target": "Death Note", "type": "manga", "creator": "Tsugumi Ohba",
        "ref_type": "thematic", "strength": 0.85,
        "themes": "god_complex,morality,descent,brilliance",
        "deep_mind": "Light Yagami and Griffith share the most dangerous trait: the absolute certainty that they are right. Both start as brilliant idealists. Both end as gods who've forgotten what humanity feels like.",
        "cinephile": "Ohba and Miura both mastered the art of the protagonist you root against. The craft of making the audience complicit in a character's descent.",
        "pop_oracle": "Light Yagami and Griffith would absolutely be in each other's DMs. 'Hey, I also sacrificed everyone for my dream.' Power couple of fictional sociopaths.",
    },
    {
        "target": "Attack on Titan", "type": "manga", "creator": "Hajime Isayama",
        "ref_type": "thematic", "strength": 0.85,
        "themes": "freedom,sacrifice,cycle_of_violence,fate",
        "deep_mind": "Eren and Guts both discover the same terrible truth: freedom is not the absence of chains, but the willingness to become the monster that breaks them.",
        "cinephile": "Isayama openly cited Berserk as his biggest influence. The panel composition of the Rumbling mirrors the Eclipse. Student and master, same visual language of apocalypse.",
        "pop_oracle": "Eren is Griffith but he at least cried about it. Both did 'I will sacrifice everything for my dream' but Eren had the decency to feel bad. Barely.",
    },
    # --- CULTURAL EVENTS (Pop Oracle exclusive) ---
    {
        "target": "Elon Musk Twitter Acquisition", "type": "cultural_event", "creator": None,
        "ref_type": "cultural", "strength": 0.7,
        "themes": "ambition,sacrifice,leadership,hubris",
        "deep_mind": None,
        "cinephile": None,
        "pop_oracle": "Griffith buying the Eclipse is Elon buying Twitter. Both had a vision, both sacrificed loyal followers, and both ended up ruling over ruins. The difference is Griffith's plan actually worked.",
    },
    {
        "target": "Kanye West Career Arc", "type": "cultural_event", "creator": None,
        "ref_type": "cultural", "strength": 0.75,
        "themes": "genius,self_destruction,public_fall,ego",
        "deep_mind": None,
        "cinephile": None,
        "pop_oracle": "Kanye went from 'College Dropout' beloved genius to burning every bridge he had. That's literally Griffith's character arc but with sneakers instead of a Behelit.",
    },
    {
        "target": "Taylor Swift Eras Tour", "type": "cultural_event", "creator": None,
        "ref_type": "cultural", "strength": 0.65,
        "themes": "reinvention,legacy,cultural_impact",
        "deep_mind": None,
        "cinephile": None,
        "pop_oracle": "Taylor Swift reinvents herself every era. Guts reinvents himself every arc. Both are about survival through transformation. Except Taylor's version doesn't involve a giant sword.",
    },
]

for ref in refs:
    conn.execute("""INSERT INTO cross_references
        (source_work, source_type, target_work, target_type, target_creator,
         reference_type, description_deep_mind, description_cinephile, description_pop_oracle,
         themes, strength)
        VALUES ('Berserk', 'manga', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (ref["target"], ref["type"], ref.get("creator"),
         ref["ref_type"], ref.get("deep_mind"), ref.get("cinephile"), ref.get("pop_oracle"),
         ref["themes"], ref["strength"]))

conn.commit()
count = conn.execute("SELECT COUNT(*) FROM cross_references").fetchone()[0]
print(f"Seeded {count} cross-references for Berserk\n")

for row in conn.execute("SELECT target_work, target_type, reference_type, strength FROM cross_references ORDER BY strength DESC"):
    print(f"  Berserk <-> {row[0]:30s} ({row[1]:15s}) [{row[2]:10s}] {row[3]}")
