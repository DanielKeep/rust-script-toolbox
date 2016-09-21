#!/usr/bin/env run-cargo-script
/*!
Run this script with `cargo script`.

```cargo
[package]
authors = ["Daniel Keep <daniel.keep@gmail.com>"]
version = "0.1.0"

[features]
trace-logging = ["env_logger", "log"]

[dependencies]
clap = "2.13.0"
env_logger = { version = "0.3.5", optional = true }
log = { version = "0.3.6", optional = true }
```
*/
/*
Copyright ⓒ 2016 Daniel Keep.

Licensed under the MIT license (see LICENSE or <http://opensource.org
/licenses/MIT>) or the Apache License, Version 2.0 (see LICENSE of
<http://www.apache.org/licenses/LICENSE-2.0>), at your option. All
files in the project carrying such notice may not be copied, modified,
or distributed except according to those terms.
*/
#[macro_use] extern crate clap;
#[cfg(feature="trace-logging")] #[macro_use] extern crate log;
#[cfg(feature="trace-logging")] extern crate env_logger;

use std::error::Error as StdError;
use std::fs;
use std::io;
use std::path::{Path, PathBuf};
use std::result::Result as StdResult;

/// Base documentation URI.  Use `*` for the latest version.
const DOC_URI: &'static str = "https://docs.rs/$CRATE/*/$CRATESAFE/$TAIL";

/**
Source file URI.  The reason we aren't more accurate is that docs.rs changes the *structure* of the URIs, and trying to get that exactly right would just be a PITA.

So I don't bother.
*/
const SRC_URI: &'static str = "https://docs.rs/crate/$CRATE/";

#[cfg(feature="trace-logging")]
macro_rules! trace_ { ($($args:tt)*) => { trace!($($args)*) } }
#[cfg(not(feature="trace-logging"))]
macro_rules! trace_ { ($($args:tt)*) => {} }

type Result<T> = StdResult<T, Error>;
type Error = Box<StdError>;

#[derive(Debug)]
struct Args {
    crate_name: String,
    delete_others: bool,
    doc_root: PathBuf,
    dry_run: bool,
}

fn main() {
    use std::io::Write;

    {
        #[cfg(feature="trace-logging")]
        macro_rules! env_logger_init {
            () => {
                if let Err(err) = env_logger::init() {
                    let _ = writeln!(std::io::stderr(), "warning: failed to initialise logging: {}", err);
                }
            }
        }

        #[cfg(not(feature="trace-logging"))]
        macro_rules! env_logger_init {
            () => {}
        }

        env_logger_init!();
    }

    match try_main() {
        Ok(()) => (),
        Err(err) => {
            let _ = writeln!(std::io::stderr(), "error: {}", err);
            std::process::exit(1);
        }
    }
}

fn try_main() -> Result<()> {
    let args = try!(get_args());
    let crate_safe_name = args.crate_name.replace("-", "_");

    {
        let dir = args.doc_root.join(&crate_safe_name);
        let base_uri = DOC_URI
            .replace("$CRATESAFE", &crate_safe_name)
            .replace("$CRATE", &args.crate_name)
            ;
        println!("Rewriting {}...", dir.display());
        try!(rewrite_dir(&args, &dir, &base_uri));
    }

    {
        let dir = args.doc_root.join("src").join(&crate_safe_name);
        let base_uri = SRC_URI
            .replace("$CRATESAFE", &crate_safe_name)
            .replace("$CRATE", &args.crate_name)
            ;
        println!("Rewriting {}...", dir.display());
        try!(rewrite_dir(&args, &dir, &base_uri));
    }

    if args.delete_others {
        let dir = args.doc_root.join("implementors").join(&crate_safe_name);
        if dir.is_dir() {
            println!("Removing {}...", dir.display());
            if !args.dry_run {
                try!(fs::remove_dir_all(&dir));
            }
        }
    }

    println!("Done.");

    if args.delete_others {
        println!("You may also wish to remove files in {}.", args.doc_root.display());
    }

    if args.dry_run {
        println!("Dry run complete; see `--help` for details.")
    }

    Ok(())
}

fn rewrite_dir(args: &Args, dir: &Path, base_uri: &str) -> Result<()> {
    trace_!("rewrite_dir(_, {:?}, {:?}) {{", dir, base_uri);
    for de in try!(fs::read_dir(dir)) {
        let de = try!(de);
        let fpath = de.path();
        let ftype = try!(de.file_type());
        let fname = try!(fpath.file_name()
            .and_then(|s| s.to_str())
            .ok_or_else(|| format!("couldn't get file name from {:?}", fpath))
        );

        if ftype.is_dir() {
            let new_uri = base_uri.replace("$TAIL", &format!("{}/$TAIL", fname));
            try!(rewrite_dir(args, &fpath, &new_uri));
        } else if ftype.is_file() {
            if fname.ends_with(".html") {
                let new_uri = base_uri.replace("$TAIL", fname);
                try!(rewrite_html(args, &fpath, &new_uri));
            } else {
                if args.delete_others {
                    print!("- rm {}", fpath.display());
                    try!(flush());
                    if !args.dry_run {
                        try!(fs::remove_file(&fpath));
                    }
                    println!("");
                }
            }
        }
    }
    trace_!("rewrite_dir(_, {:?}, {:?}) }}", dir, base_uri);
    Ok(())
}

fn rewrite_html(args: &Args, path: &Path, uri: &str) -> Result<()> {
    trace_!("rewrite_html(_, {:?}, {:?})", path, uri);
    use std::io::Write;

    let body = REDIR_TEMPLATE
        .replace("$CRATE", &args.crate_name)
        .replace("$DEST", uri)
        ;

    print!("- redir {}", path.display());
    try!(flush());
    if !args.dry_run {
        let mut f = try!(fs::File::create(path));
        try!(f.write_all(body.as_bytes()));
        try!(f.sync_all());
    }
    println!(" -> {}", uri);
    Ok(())
}

fn get_args() -> Result<Args> {
    use clap::Arg;
    let matches = clap::App::new("redirect-to-docs.rs")
        .version(crate_version!())
        .author(crate_authors!())
        .about("Rewrites all HTML files in rustdoc-generated documentation \
            to point to `https://docs.rs/` instead.")
        .after_help("By default, performs a dry run, listing everything it \
            intends to do.  You should review this output and then re-run \
            with the --commit flag.")
        .arg(Arg::with_name("commit")
            .long("commit")
            .help("Actually take the requested actions, instead of performing a dry run.")
        )
        .arg(Arg::with_name("crate_name")
            .long("crate-name")
            .value_name("NAME")
            .takes_value(true)
            .required(true)
            .help("Manually specify the name of the crate being documented.")
        )
        .arg(Arg::with_name("delete_others")
            .long("delete-others")
            .help("Delete other, non-HTML files.")
        )
        .arg(Arg::with_name("doc_root")
            .long("doc-root")
            .value_name("PATH")
            .takes_value(true)
            .required(true)
            .help("Manually specify the root directory for the crate documentation.")
        )
        .get_matches();

    let commit = matches.is_present("commit");
    let crate_name = matches.value_of("crate_name").map(String::from).unwrap();
    let delete_others = matches.is_present("delete_others");
    let doc_root = matches.value_of("doc_root").map(PathBuf::from).unwrap();

    Ok(Args {
        crate_name: crate_name,
        delete_others: delete_others,
        doc_root: doc_root,
        dry_run: !commit,
    })
}

fn flush() -> io::Result<()> {
    use std::io::Write;
    std::io::stdout().flush()
}

const REDIR_TEMPLATE: &'static str = r##"<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>$CRATE</title>
    <style type="text/css">

        body {
            font-family: sans-serif;
            position: absolute;
            top: 40%;
            left: 50%;
            margin-right: -50%;
            transform: translate(-50%, -50%);
            margin-left: auto;
            margin-top: auto;
            margin-bottom: auto;
        }

    </style>
    <meta http-equiv="refresh" content="0; url=$DEST">
</head>
<body>
    <h1><a href="$DEST">Content Moved</a></h1>
    <p>This documentation is now being hosted on <a href="https://docs.rs/">docs.rs</a>.  <a href="$DEST">Follow the redirection</a> if it does not work automatically.</p>
</body>
</html>
"##;
