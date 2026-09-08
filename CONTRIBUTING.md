# How to contribute

Wilmer is a passion project, and one that is shared so that everyone can enjoy it. Contributions are always welcome.  
It's always been the hope that smart folks who have amazing ideas will bring them and make this thing so much better.

Here are some resources to get you start

* The main [User Documents Readme](/Docs/User_Documentation/README.md) will tell you what this project is all about
* The [Developer Docs](Docs/Developer_Docs) have a (hopefully) up-to-date breakdown of many features and code sections
  to help you find your
  way around the codebase
* There are [unit tests](Tests)!

## Testing

Use Python 3.13.14 or a later 3.13 patch, or 3.14.5 or a later 3.14 patch, and activate the project environment.
The `.python-version` file records the development default, not the only version that can run the tests. See the
[test environment setup](Docs/Developer_Docs/Features_And_Packages/Unit_Tests.md#1-environment-setup) for instructions.

Testing is done via Pytest. You can run them by

* pip install -r requirements-test.txt
* running `pytest --cov=Middleware` to run the full battery of tests

## Submitting a Pull Request

* Requests should be targeted. Sweeping PRs of 5 or 6 features, filled with unrelated changes to
  those features, will be almost impossible to code review properly and will be denied (or worse,
  ignored)


* Please add targeted and good unit tests for all changes.
* Please avoid making changes to existing unit tests to fit your updates.
    * If you do, please explain exactly why in the pull request.
* Do not leave calls to websites in your unit tests.
* Unit tests should not modify the user's machine in any way, and should leave no trace.
  Mock everything.


* Please avoid adding any code that quietly makes calls to external websites. This is a
  locally run and private application. That's not to say nothing can make external web
  calls, but make it overt and something the user is certain to know is occurring.
* Do not make changes that will affect other programs outside of Wilmer.


* Update Developer and User documentation if you make feature changes. Keep the changes targeted
* Make sure your github user is appropriately tied to the commits, or you won't show up on
  the contributor list.


* Unit tests must pass for a PR to be completed.

## Coding conventions

* Middleware is basically src; keep the code in there unless you're adding external scripts,
  like custom python scripts for folks.
* Match the docstring format
* Look around; you'll see patterns you can follow. There may be places where the current code doesn't
  fit its own pattern; that will hopefully be fixed soon. But try to make new code fit it.
* A lot of stuff here will be spelled out in developer docs.

Thanks so much for contributing! It really means a lot.

- Chris *(SomeOddCodeGuy)*
