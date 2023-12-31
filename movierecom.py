# -*- coding: utf-8 -*-
from google.colab import drive, files
drive.mount('/content/drive')

files.upload()

!pip install -q kaggle
!mkdir ~/.kaggle
!cp kaggle.json ~/.kaggle/
!chmod 600 ~/.kaggle/kaggle.json

!kaggle datasets download -d rounakbanik/the-movies-dataset

!unzip the-movies-dataset.zip -d /content/data

!rm the-movies-dataset.zip

!pip install --quiet fastparquet
!pip install --quiet pyarrow

# Commented out IPython magic to ensure Python compatibility.
# %matplotlib inline
import pandas as pd
import numpy as np

from ast import literal_eval
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from nltk.stem.snowball import SnowballStemmer

import pyarrow as pa
import pyarrow.parquet as pq

import warnings
warnings.simplefilter('ignore')



"""
    Here we take the name of the director to showcase it to the user
"""
def get_director(x):

    for i in x:
        if i['job'] == 'Director':
            return i['name']
    return np.nan

movies_dataset  = pd.read_csv('/content/data/movies_metadata.csv')
credits         = pd.read_csv('/content/data/credits.csv')
keywords        = pd.read_csv('/content/data/keywords.csv')
links           = pd.read_csv('/content/data/links.csv')


## Dropping these 3 rows because Date Column value for them is string date instead of Int with ID.
movies_dataset = movies_dataset.drop([19730, 29503, 35587])


## Extracting Genres of movies from the genres dictionary. If not present we append empty list
movies_dataset['genres'] = movies_dataset['genres'].fillna('[]').apply(literal_eval).apply(lambda x: [i['name'] for i in x] if isinstance(x, list) else [])


## Convert to common data type for primary key in our dataset
keywords['id'] = keywords['id'].astype('int')
credits['id'] = credits['id'].astype('int')
movies_dataset['id'] = movies_dataset['id'].astype('int')


## Merging movies dataset with credits & keywords to form master dataset
movies_dataset = movies_dataset.merge(credits, on='id')
master_dataset = movies_dataset.merge(keywords, on='id')


master_dataset.head(2)

print(master_dataset.columns)

links = links[links['tmdbId'].notnull()]['tmdbId'].astype('int')
master_dataset = master_dataset[master_dataset['id'].isin(links)]
print(master_dataset.shape)

## Updating cast, crew and keyword columns by parsing them as their loaded data type is string but need to be converted to list
master_dataset['cast']      = master_dataset['cast'].apply(literal_eval)
master_dataset['crew']      = master_dataset['crew'].apply(literal_eval)
master_dataset['keywords  ']  = master_dataset['keywords'].apply(literal_eval)


## Updating cast to maintain proportion between different lengths (keeping top 3 cast members)
master_dataset['cast']      = master_dataset['cast'].apply(lambda x: [i['name'] for i in x] if isinstance(x, list) else [])
master_dataset['cast']      = master_dataset['cast'].apply(lambda x: x[:3] if len(x) >=3 else x)

## Setting keywords to empty list if does not exists, otherwise taking into account for each word as keyword
master_dataset['keywords']  = master_dataset['keywords'].apply(lambda x: [i['name'] for i in x] if isinstance(x, list) else [])

## Extracting directory names from the crew
master_dataset['director']  = master_dataset['crew'].apply(get_director)


## for uniqueness, removing all the spaces in between the names
master_dataset['cast']          = master_dataset['cast'].apply(lambda x: [str.lower(i.replace(" ", "")) for i in x])

## Maintaining the original director name as main director
master_dataset['main_director'] = master_dataset['director']

## Maintaining the number of director to maintain proportion (similar to cast column above)
master_dataset['director']      = master_dataset['director'].astype('str').apply(lambda x: str.lower(x.replace(" ", "")))
master_dataset['director']      = master_dataset['director'].apply(lambda x: [x,x,x])


## Stacking the keywords and keeping the movies which containers X number of keywords as minimum
s = master_dataset.apply(lambda x: pd.Series(x['keywords']),axis=1).stack().reset_index(level=1, drop=True)
s.name = 'keyword'
s = s.value_counts()
print(s[:5])

## Will try to map where more than 1 keyword is present for the movie
s = s[s > 1]


## creating an object for ENGLISH Stemmer - Snowball to trim down keywords to their stem words
stemmer                     = SnowballStemmer('english')

## Trim down keywords to their stem words and then remove the space between keywords which are having more than 1 length for uniqueness
master_dataset['keywords']  = master_dataset['keywords'].apply(lambda x: [stemmer.stem(i) for i in x])
master_dataset['keywords']  = master_dataset['keywords'].apply(lambda x: [str.lower(i.replace(" ", "")) for i in x])


master_dataset['keywords'].head(3)

## Creating a soup feature - combination of (keywords, cast, director, genres)
master_dataset['soup'] = master_dataset['keywords'] + master_dataset['cast'] + master_dataset['director'] + master_dataset['genres']

## Modifying by placing single space between all the soup words
master_dataset['soup'] = master_dataset['soup'].apply(lambda x: ' '.join(x))


master_dataset['soup'].head(3)

print(master_dataset.columns)

## Removing unwanted columns from the dataset - these features can be used if you wish to add more features to your recommender system.
## We are not going to use them, so we are removing them.
master_dataset.drop(['adult', 'belongs_to_collection', 'budget','homepage','original_language', 'production_companies','production_countries', 'revenue', 'runtime','spoken_languages','status','video'],axis=1,inplace=True)
master_dataset.drop(['overview', 'tagline','vote_average', 'vote_count', 'cast', 'crew','keywords', 'director'],axis=1,inplace=True)
master_dataset.drop(['id','imdb_id','original_title','poster_path','genres'],axis=1,inplace=True)


## Checking popularity column for being non-float data type and removing them
master_dataset['popularity']    = master_dataset.apply(lambda r: r['popularity'] if type(r['popularity'])==float else np.nan, axis=1)
master_dataset.dropna(inplace=True)

## Checking director column for being non-string data type and removing them
master_dataset['main_director'] = master_dataset.apply(lambda r: r['main_director'] if len(r['main_director'])>1 else np.nan, axis=1)
master_dataset.dropna(inplace=True)


## Sorting the whole dataset based on popularity. This will help us to take top X number of movies based on popularity.
master_dataset.sort_values(by=['popularity'],ascending=False,inplace=True)

## Dropping popularity column after sorting based on popularity
master_dataset.drop(['popularity'],axis=1,inplace=True)
master_dataset.dropna(inplace=True)

## Reset index because after sorting, the index values have changed.
master_dataset.reset_index(inplace=True,drop=True)


## Checking release date column for being non-string data type and removing them
master_dataset['release_date'] = master_dataset.apply(lambda r: r['release_date'] if len(r['release_date'])>1 else np.nan, axis=1)
master_dataset.dropna(inplace=True)

## For Demo, we will take top 2500 movies, which is hosted online already.
master_dataset = master_dataset[:2500]

## This is our final dataset which we will be using for training our word and cosine similarity matrix
master_dataset.head()

print(master_dataset.shape)

## Creating a Count Vectorizer object which will be based on word analyzer, with ngram 1-2 and minimum number of occurances of words as 2
count = CountVectorizer(analyzer='word',ngram_range=(1, 2),min_df=2, stop_words='english')

## Adjusting the count vectorizer object with respect to our dataset
count_matrix = count.fit_transform(master_dataset['soup'])


print(count_matrix.shape)

## We build it as an pyarrow dataframe because it is the most efficient
table = pa.Table.from_pandas(pd.DataFrame(cosine_similarity(count_matrix, count_matrix)))

## save the Master Dataset
master_dataset.to_parquet('/content/movie_database.parquet',engine='fastparquet',index=False)


## Writing the Matrix table
pq.write_table(table, '/content/model.parquet')

import pandas as pd
import pyarrow as pa


master_dataset = pd.read_parquet('/content/movie_database.parquet')


master_dataset.head(3)

table = pa.parquet.read_table('/content/model.parquet').to_pandas()


master_dataset = master_dataset.reset_index()
titles = master_dataset['title']
indices = pd.Series(master_dataset.index, index=master_dataset['title'])


def get_recommendations(movie_id_from_db,movie_db):
    try:
        sim_scores = list(enumerate(movie_db[movie_id_from_db]))
        sim_scores = sorted(sim_scores, key=lambda x: x[1], reverse=True)
        sim_scores = sim_scores[1:15] ## get top 15 Recommendations

        movie_indices = [i[0] for i in sim_scores]
        output = master_dataset.iloc[movie_indices]
        output.reset_index(inplace=True, drop=True)

        response = []
        for i in range(len(output)):
            response.append({
                'movie_title':output['title'].iloc[i],
                'movie_release_date':output['release_date'].iloc[i],
                'movie_director':output['main_director'].iloc[i],
                'google_link':"https://www.google.com/search?q=" + '+'.join(output['title'].iloc[i].strip().split())
            })
        return response
    except Exception as e:
        print("error: ",e)
        return []


movie_name = input('Enter a movie Name: ')

movie_index = titles.to_list().index(movie_name)
recommendations = get_recommendations(movie_index,table)


print(f"{'Movie Title':<40} | {'Director':<20} | {'Release Date':<15}")
print(f"-"*80)
for recommendation in recommendations:
    ans =print(f"{recommendation['movie_title']:<40} | {recommendation['movie_director']:<20} | {recommendation['movie_release_date']:<15}")
