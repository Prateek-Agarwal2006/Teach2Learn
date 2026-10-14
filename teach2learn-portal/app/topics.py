"""Dataset-derived subject, topic, and subtopic catalogue."""

from __future__ import annotations

import re


MODELS = [
    {"id": "qwen3", "name": "Qwen3 8B"},
    {"id": "qwen2.5", "name": "Qwen 2.5 7B"},
    {"id": "granite42", "name": "Granite 4.2 8B"},
    {"id": "llama31", "name": "Llama 3.1 8B"},
]


TOPICS: dict[str, dict[str, object]] = {
    "cp": {"name": "Computer Programming", "topics": {
        "foundations": {"name": "Programming foundations", "subtopics": ["Computers and programming languages", "Algorithms and pseudocode", "Compilation, testing, and debugging"]},
        "c-basics": {"name": "C fundamentals", "subtopics": ["Types, variables, and constants", "Operators and expressions", "Console input and output"]},
        "control-flow": {"name": "Control flow", "subtopics": ["Conditions and switch statements", "Loops and sentinel values", "Input validation"]},
        "functions": {"name": "Functions and modularity", "subtopics": ["Parameters and return values", "Scope and storage classes", "Headers and libraries"]},
        "pointers": {"name": "Pointers and memory", "subtopics": ["Addresses and pointers", "Pointer arithmetic", "Dynamic memory allocation"]},
        "arrays-strings": {"name": "Arrays and strings", "subtopics": ["Arrays and matrices", "Searching, sorting, and parallel arrays", "Characters and strings"]},
        "structured": {"name": "Structured programming", "subtopics": ["Recursion", "Structures and unions", "Abstract data types"]},
        "files-structures": {"name": "Files and dynamic structures", "subtopics": ["Text and binary files", "Linked lists", "Stacks and queues"]},
    }},
    "dsa": {"name": "Data Structures and Algorithms", "topics": {
        "analysis": {"name": "Algorithm analysis", "subtopics": ["Asymptotic notation", "Recurrences", "Average and randomized analysis"]},
        "linear": {"name": "Linear data structures", "subtopics": ["Arrays and linked lists", "Stacks", "Queues and deques"]},
        "trees-heaps": {"name": "Trees and priority queues", "subtopics": ["Tree terminology and traversals", "Heaps", "Priority queues"]},
        "maps": {"name": "Maps and hashing", "subtopics": ["Dictionaries and maps", "Hash functions", "Collision resolution"]},
        "search": {"name": "Search structures", "subtopics": ["Binary search trees", "Balanced search trees", "Skip lists"]},
        "design": {"name": "Sorting and design techniques", "subtopics": ["Sorting and selection", "Divide and conquer", "Greedy and dynamic programming"]},
        "graphs": {"name": "Graph foundations", "subtopics": ["Graph representations", "DFS and BFS", "Connectivity and directed graphs"]},
        "graph-optimization": {"name": "Graph optimization", "subtopics": ["Shortest paths", "Minimum spanning trees", "Network flows and matching"]},
        "text-numeric": {"name": "Text and numeric algorithms", "subtopics": ["Tries and string processing", "Sequence algorithms", "Number theory and cryptography"]},
        "advanced": {"name": "Advanced algorithms", "subtopics": ["Computational geometry", "Distributed and parallel algorithms", "NP-completeness and approximation"]},
    }},
    "oop_java": {"name": "Object-Oriented Programming with Java", "topics": {
        "java-foundations": {"name": "Java foundations", "subtopics": ["JVM and language basics", "Types and operators", "Control flow"]},
        "classes": {"name": "Classes and objects", "subtopics": ["Fields and methods", "Constructors", "Access control and object identity"]},
        "oop-design": {"name": "Object-oriented design", "subtopics": ["Inheritance", "Polymorphism", "Abstract classes and interfaces"]},
        "packages-exceptions": {"name": "Packages and exceptions", "subtopics": ["Packages and inner classes", "Exception handling", "Custom exceptions"]},
        "concurrency": {"name": "Concurrency", "subtopics": ["Threads", "Synchronization and locks", "Executors and concurrency utilities"]},
        "language-features": {"name": "Java language features", "subtopics": ["Enumerations and autoboxing", "Annotations and reflection", "Generics and lambdas"]},
        "collections": {"name": "Collections and streams", "subtopics": ["Lists, sets, and maps", "Iterators", "Stream API"]},
        "io": {"name": "Input and output", "subtopics": ["Streams and serialization", "Files and paths", "NIO"]},
        "networking": {"name": "Networking and text", "subtopics": ["Sockets and URLs", "Processes", "Regular expressions"]},
        "interfaces": {"name": "User interfaces and web", "subtopics": ["AWT and events", "Swing and JavaFX", "JavaBeans and servlets"]},
    }},
    "os": {"name": "Operating Systems", "topics": {
        "foundations": {"name": "OS foundations", "subtopics": ["Purpose and services", "Architecture and operating modes", "System calls"]},
        "processes": {"name": "Processes and communication", "subtopics": ["Process lifecycle", "Interprocess communication", "Shared memory and message passing"]},
        "threads-scheduling": {"name": "Threads and scheduling", "subtopics": ["Multithreading", "CPU scheduling", "Multiprocessor scheduling"]},
        "synchronization": {"name": "Synchronization", "subtopics": ["Critical sections", "Semaphores and monitors", "Locks and atomic operations"]},
        "deadlocks": {"name": "Deadlocks and transactions", "subtopics": ["Deadlock conditions", "Prevention and avoidance", "Detection and recovery"]},
        "memory": {"name": "Memory management", "subtopics": ["Memory allocation", "Paging and segmentation", "Kernel memory"]},
        "virtual-memory": {"name": "Virtual memory", "subtopics": ["Demand paging", "Page replacement", "Thrashing"]},
        "files": {"name": "Files and directories", "subtopics": ["File operations", "Directories", "Access control and locking"]},
        "file-systems": {"name": "File-system implementation", "subtopics": ["Allocation and free space", "Recovery and journaling", "Network file systems"]},
        "storage-io": {"name": "Storage and I/O", "subtopics": ["Disk scheduling", "RAID", "Controllers, drivers, and I/O"]},
        "security-distributed": {"name": "Security and distributed systems", "subtopics": ["Protection and authentication", "System security", "Distributed coordination"]},
        "special-systems": {"name": "Special systems and case studies", "subtopics": ["Real-time systems", "Linux and Windows", "Mach and historical systems"]},
    }},
}


_ALIASES = {
    "computer_programming": "cp", "programming": "cp", "c": "cp",
    "data_structures_and_algorithms": "dsa", "data_structures": "dsa",
    "oop": "oop_java", "java": "oop_java", "oop_and_java": "oop_java", "object_oriented_programming": "oop_java",
    "operating_systems": "os", "operating_system": "os",
}


def normalize_subject(subject: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", subject.strip().lower()).strip("_")
    key = _ALIASES.get(key, key)
    if key not in TOPICS:
        raise ValueError(f"Unknown subject: {subject!r}")
    return key


def subjects() -> list[dict[str, object]]:
    return [{"id": slug, "name": details["name"]} for slug, details in TOPICS.items()]


def topics_for(subject: str) -> list[str]:
    topic_map = TOPICS[normalize_subject(subject)]["topics"]
    if not isinstance(topic_map, dict):
        return []
    return [str(item["name"]) for item in topic_map.values() if isinstance(item, dict)]


def topic_selection(subject: str, topic_id: str, subtopic: str) -> tuple[str, str]:
    topic_map = TOPICS[normalize_subject(subject)]["topics"]
    if not isinstance(topic_map, dict) or topic_id not in topic_map:
        raise ValueError("Unknown topic")
    topic = topic_map[topic_id]
    if not isinstance(topic, dict) or subtopic not in topic["subtopics"]:
        raise ValueError("Unknown subtopic")
    return str(topic["name"]), subtopic
