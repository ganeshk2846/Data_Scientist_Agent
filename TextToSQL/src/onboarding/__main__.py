"""Run the BE-2 SQLite onboarding pipeline."""
import argparse
import json
import sys

from .pipeline import approve_review, build_catalog, review_descriptions
from .health import health_report
from src.knowledge.semantic_models import SentenceTransformerEmbedder


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="build or resume a warehouse catalog")
    build.add_argument("--warehouse", required=True)
    build.add_argument("--output", default="artifacts/catalog")
    build.add_argument("--mask", action="append", default=[], help="fully qualified sensitive column, e.g. customer.email")
    build.add_argument("--learned-embeddings", action="store_true",
                       help="use the pinned all-MiniLM-L6-v2 model from local cache only")
    approve = sub.add_parser("review", help="record human decisions; rerun build to publish")
    approve.add_argument("--output", default="artifacts/catalog")
    approve.add_argument("--approve-join", action="append", default=[])
    approve.add_argument("--reject-join", action="append", default=[])
    approve.add_argument("--approve-sensitive", action="append", default=[])
    approve.add_argument("--reject-sensitive", action="append", default=[])
    approve.add_argument("--dismiss-sensitive", action="append", default=[])
    approve.add_argument("--approve-description", action="append", default=[],
                         metavar="TARGET=TEXT", help="approve a table or table.column description")
    approve.add_argument("--reject-description", action="append", default=[],
                         metavar="TARGET", help="reject a table or table.column description")
    approve.add_argument("--reviewer", required=True,
                         help="reviewer identity supplied by the authenticated host; never use a placeholder")
    health = sub.add_parser("health", help="check local runtime/configuration readiness without network calls")
    health.add_argument("--root", help="data/service root to inspect (defaults to TEXTTOSQL_DATA_ROOT or cwd)")
    args = parser.parse_args()
    if args.command == "health":
        report = health_report(args.root)
        print(json.dumps(report, indent=2))
        if not report["ready"]:
            sys.exit(1)
    elif args.command == "build":
        encoder = SentenceTransformerEmbedder.load_local() if args.learned_embeddings else None
        result = build_catalog(args.warehouse, args.output, sensitive_columns=args.mask,
                               dense_encoder=encoder)
        print(json.dumps(result, indent=2))
    else:
        approve_review(args.output, approve_joins=args.approve_join, reject_joins=args.reject_join, approve_sensitive=args.approve_sensitive, reject_sensitive=args.reject_sensitive + args.dismiss_sensitive, reviewer=args.reviewer)
        approved_descriptions = {}
        for item in args.approve_description:
            target, separator, text = item.partition("=")
            if not separator or not target.strip() or not text.strip():
                parser.error("--approve-description must be TARGET=TEXT")
            approved_descriptions[target.strip()] = text.strip()
        if approved_descriptions or args.reject_description:
            review_descriptions(args.output, approve=approved_descriptions,
                                reject=args.reject_description, reviewer=args.reviewer)
        print("Review decisions recorded. Rerun the build to publish them.")


if __name__ == "__main__":
    main()
